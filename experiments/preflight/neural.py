"""Small CPU neural intent classifier with TRAIN-only fitting and no TEST access.

This model supplies bounded nonlinear update chains; it is trained from scratch
and does not stand in for pretrained transformers or LoRA. Torch is isolated in
``experiments/neural`` and imported lazily so the existing CPU pilot stays usable.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import platform
import re
import resource
import subprocess
import time

import numpy as np

from .data import normalize_text
from .runner import canonical, digest, file_hash, utc, write_json

DEFAULT_NEURAL_CONFIG = {
    'architecture': 'word-mean-embedding-relu-mlp',
    'embedding_dim': 64, 'hidden_dim': 64, 'dropout': 0.0,
    'optimizer': 'Adam', 'learning_rate': 0.003, 'weight_decay': 0.0,
    'batch_size': 128, 'vocabulary_limit': 12000, 'min_frequency': 1,
    'max_length': 40, 'threads': 2, 'device': 'cpu',
    'tokenizer': 'nfkc-space-casefold-unicode-word-or-punctuation-v1',
}


def _torch():
    try:
        import torch
    except ImportError as error:
        raise RuntimeError('ISOLATED_NEURAL_ENVIRONMENT_REQUIRED') from error
    return torch


def _config(config):
    config = deepcopy(DEFAULT_NEURAL_CONFIG if config is None else config)
    if set(config) != set(DEFAULT_NEURAL_CONFIG):
        raise ValueError('NEURAL_CONFIG_KEYS_MISMATCH')
    for key in ['embedding_dim', 'hidden_dim', 'batch_size', 'vocabulary_limit', 'min_frequency', 'max_length', 'threads']:
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError('INVALID_NEURAL_POSITIVE_INTEGER')
    if config['vocabulary_limit'] < 3:
        raise ValueError('INVALID_NEURAL_VOCABULARY_LIMIT')
    if config['architecture'] != DEFAULT_NEURAL_CONFIG['architecture'] or config['tokenizer'] != DEFAULT_NEURAL_CONFIG['tokenizer'] or config['optimizer'] != 'Adam' or config['device'] != 'cpu' or config['dropout'] != 0.0:
        raise ValueError('UNSUPPORTED_NEURAL_CONTRACT')
    if type(config['learning_rate']) not in (int, float) or not math.isfinite(config['learning_rate']) or config['learning_rate'] <= 0 or type(config['weight_decay']) not in (int, float) or not math.isfinite(config['weight_decay']) or config['weight_decay'] < 0:
        raise ValueError('INVALID_NEURAL_OPTIMIZER_CONFIG')
    return config


def tokenize(text):
    if not isinstance(text, str):
        raise ValueError('NEURAL_TEXT_MUST_BE_STRING')
    return re.findall(r'\w+|[^\w\s]', normalize_text(text).casefold(), flags=re.UNICODE)


def _train_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('NONEMPTY_TRAIN_ROWS_REQUIRED')
    ids = []
    for row in rows:
        if not isinstance(row, dict) or row.get('role') != 'TRAIN' or not all(isinstance(row.get(key), str) and row[key] for key in ('sample_id', 'text', 'gold_label')):
            raise ValueError('TRAIN_ONLY_REQUIRED')
        ids.append(row['sample_id'])
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_TRAIN_SAMPLE_ID')


def build_vocabulary(rows, config=None):
    """Build lexical state from the supplied TRAIN basis, never DEV text."""
    config = _config(config)
    _train_rows(rows)
    counts = Counter(token for row in rows for token in tokenize(row['text']))
    ordered = sorted((word for word, count in counts.items() if count >= config['min_frequency']), key=lambda word: (-counts[word], word.encode('utf-8')))
    # Reserved IDs are integers without lexical spellings that can collide.
    return {word: index + 2 for index, word in enumerate(ordered[:config['vocabulary_limit']-2])}


def _vocabulary(vocabulary, config):
    if not isinstance(vocabulary, dict) or any(not isinstance(token, str) or not token or type(index) is not int for token, index in vocabulary.items()) or sorted(vocabulary.values()) != list(range(2, len(vocabulary)+2)) or len(vocabulary)+2 > config['vocabulary_limit']:
        raise ValueError('INVALID_NEURAL_VOCABULARY')


def _encode(texts, vocabulary, config):
    torch = _torch()
    result = torch.zeros((len(texts), config['max_length']), dtype=torch.long)
    for index, text in enumerate(texts):
        ids = [vocabulary.get(token, 1) for token in tokenize(text)[:config['max_length']]] or [1]
        result[index, :len(ids)] = torch.tensor(ids, dtype=torch.long)
    return result


def _model(vocabulary_size, label_count, config):
    torch = _torch()
    class MeanMLP(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(vocabulary_size, config['embedding_dim'], padding_idx=0, dtype=torch.float32)
            self.hidden = torch.nn.Linear(config['embedding_dim'], config['hidden_dim'], dtype=torch.float32)
            self.output = torch.nn.Linear(config['hidden_dim'], label_count, dtype=torch.float32)

        def forward(self, tokens):
            embedded = self.embedding(tokens)
            denominator = (tokens != 0).sum(dim=1, keepdim=True).clamp_min(1)
            pooled = embedded.sum(dim=1) / denominator
            return self.output(torch.relu(self.hidden(pooled)))
    return MeanMLP()


def fit_neural(rows, vocabulary, labels, *, seed, epochs, config=None, max_seconds=180.0):
    """From-scratch fixed-epoch fit; inputs must contain only TRAIN rows.

    Vocabulary and label ordering belong to the frozen chain basis. Seed and
    optimizer are restarted for every slot. No stopping criterion uses DEV.
    """
    begin = time.perf_counter()
    config = _config(config)
    _train_rows(rows)
    _vocabulary(vocabulary, config)
    if not isinstance(labels, list) or len(labels) < 2 or labels != sorted(set(labels)) or any(not isinstance(label, str) or not label for label in labels) or set(row['gold_label'] for row in rows) != set(labels):
        raise ValueError('NEURAL_LABEL_CONTRACT_MISMATCH')
    if type(seed) is not int or seed < 0 or type(epochs) is not int or not 1 <= epochs <= 64 or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('INVALID_NEURAL_FIT_BUDGET')
    torch = _torch()
    torch.set_num_threads(config['threads'])
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    model = _model(len(vocabulary)+2, len(labels), config)
    x = _encode([row['text'] for row in rows], vocabulary, config)
    mapping = {label: index for index, label in enumerate(labels)}
    y = torch.tensor([mapping[row['gold_label']] for row in rows], dtype=torch.long)
    optimizer = torch.optim.Adam(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
    generator = torch.Generator(device='cpu').manual_seed(seed)
    losses = []
    for epoch in range(epochs):
        order = torch.randperm(len(rows), generator=generator)
        accumulated = 0.0
        model.train()
        for start in range(0, len(rows), config['batch_size']):
            batch = order[start:start+config['batch_size']]
            optimizer.zero_grad(set_to_none=True)
            loss = torch.nn.functional.cross_entropy(model(x[batch]), y[batch])
            if not torch.isfinite(loss):
                raise ValueError('NONFINITE_NEURAL_TRAINING_LOSS')
            loss.backward()
            optimizer.step()
            accumulated += float(loss.detach()) * len(batch)
            if time.perf_counter()-begin > max_seconds:
                raise ValueError('NEURAL_FIT_RESOURCE_BUDGET_EXCEEDED_NO_RETUNING')
        losses.append(accumulated/len(rows))
    model.eval()
    return {
        'schema_version': 'small-neural-bundle-v1', 'config': config,
        'vocabulary': dict(vocabulary), 'labels': list(labels),
        'state_dict': {name: value.detach().cpu().contiguous().clone() for name, value in model.state_dict().items()},
        'training_summary': {'seed': seed, 'epochs': epochs, 'rows': len(rows),
                             'train_ids_sha256': digest([row['sample_id'] for row in rows]),
                             'train_seconds': time.perf_counter()-begin,
                             'parameter_count': sum(value.numel() for value in model.parameters()),
                             'epoch_train_cross_entropy': losses,
                             'fixed_epoch_budget_completed': True,
                             'dev_examples_observed': 0, 'test_examples_observed': 0},
    }


def neural_probabilities(bundle, texts):
    """Predict for caller-provided text; this function never opens data files."""
    torch = _torch()
    config = _config(bundle['config'])
    _vocabulary(bundle['vocabulary'], config)
    torch.set_num_threads(config['threads'])
    # Recreating a module should not change any caller's global RNG sequence.
    with torch.random.fork_rng(devices=[]):
        model = _model(len(bundle['vocabulary'])+2, len(bundle['labels']), config)
    model.load_state_dict(bundle['state_dict'], strict=True)
    model.eval()
    x = _encode(texts, bundle['vocabulary'], config)
    values = []
    with torch.inference_mode():
        for start in range(0, len(texts), config['batch_size']):
            values.append(torch.softmax(model(x[start:start+config['batch_size']]).double(), dim=1).numpy())
    scores = np.concatenate(values) if values else np.empty((0, len(bundle['labels'])), dtype=np.float64)
    if not np.isfinite(scores).all() or not np.allclose(scores.sum(axis=1), 1, atol=1e-8, rtol=0):
        raise ValueError('INVALID_NEURAL_PROBABILITIES')
    predicted = np.asarray(bundle['labels'], dtype=str)[scores.argmax(axis=1)] if len(texts) else np.asarray([], dtype=str)
    return scores, predicted


def neural_identity(bundle):
    """Exact stored inference-state identity without inference or lexical output.

    Equality detects identical stored states. Inequality does not establish
    different functions or independent model-update observations.
    """
    config = _config(bundle['config'])
    _vocabulary(bundle['vocabulary'], config)
    weights = {}
    for name, value in sorted(bundle['state_dict'].items()):
        array = value.detach().cpu().contiguous().numpy()
        if array.dtype != np.dtype('float32') or not np.isfinite(array).all():
            raise ValueError('INVALID_NEURAL_STATE')
        encoded = np.asarray(array, dtype='<f4').tobytes()
        weights[name] = {'shape': list(array.shape), 'dtype': 'little-endian-float32', 'sha256': hashlib.sha256(encoded).hexdigest()}
    components = {
        'architecture': config['architecture'], 'embedding_dim': config['embedding_dim'],
        'hidden_dim': config['hidden_dim'], 'max_length': config['max_length'],
        'tokenizer': config['tokenizer'],
        'vocabulary': {'size': len(bundle['vocabulary'])+2, 'mapping_sha256': digest(bundle['vocabulary'])},
        'labels_sha256': digest(bundle['labels']), 'weights': weights,
    }
    return {'schema_version': 'small-neural-identity-v1', 'label_state_sha256': digest(components),
            'probability_state_sha256': digest({'components': components, 'link': 'float64-softmax'}),
            'components': components}


def save_neural(bundle, path):
    torch = _torch()
    path = Path(path)
    with path.open('xb') as stream:
        torch.save(bundle, stream)
    return file_hash(path)


def load_neural(path):
    bundle = _torch().load(Path(path), map_location='cpu', weights_only=True)
    neural_identity(bundle)
    return bundle


def resource_probe(train_rows, output, *, config=None, seed=90001, fraction=0.1, epochs=2, max_seconds=120.0, max_rss_mib=2048.0):
    """A single TRAIN-only resource observation, not an accuracy experiment."""
    from .runner import nested_train_indices
    config = _config(config)
    _train_rows(train_rows)
    output = Path(output)
    if output.exists():
        raise ValueError('NEW_RESOURCE_PROBE_DIRECTORY_REQUIRED')
    output.mkdir(parents=True)
    selected = [train_rows[index] for index in nested_train_indices(train_rows, fraction, seed)]
    labels = sorted({row['gold_label'] for row in train_rows})
    registration = {'schema_version': 'neural-train-only-resource-v1', 'registered_at': utc(),
                    'config': config, 'seed': seed, 'fraction': fraction, 'epochs': epochs,
                    'max_seconds': max_seconds, 'max_rss_mib': max_rss_mib,
                    'code_sha256': file_hash(Path(__file__)),
                    'dependency_lock_sha256': file_hash(Path(__file__).resolve().parents[1]/'neural/uv.lock'),
                    'train_rows': len(train_rows),
                    'probe_rows': len(selected), 'probe_train_ids_sha256': digest([row['sample_id'] for row in selected]),
                    'dev_allowed': False, 'test_allowed': False,
                    'purpose': 'TRAIN_ONLY_RESOURCE_PROBE_NOT_MODEL_OR_FEATURE_SELECTION'}
    write_json(output/'registration.json', registration)
    vocabulary = build_vocabulary(selected, config)
    bundle = fit_neural(selected, vocabulary, labels, seed=seed, epochs=epochs, config=config, max_seconds=max_seconds)
    restore_begin = time.perf_counter()
    save_neural(bundle, output/'probe.pt')
    restored = load_neural(output/'probe.pt')
    save_restore_seconds = time.perf_counter()-restore_begin
    texts = [row['text'] for row in selected[:32]]
    inference_begin = time.perf_counter()
    scores = neural_probabilities(bundle, texts)[0]
    inference_seconds = time.perf_counter()-inference_begin
    restore_exact = np.array_equal(scores, neural_probabilities(restored, texts)[0]) and neural_identity(bundle) == neural_identity(restored)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    try:
        observation = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,memory.used', '--format=csv,noheader,nounits'], text=True, timeout=5).strip()
        gpu = {'observed_at': utc(), 'source': 'nvidia-smi', 'fields': ['name', 'total_memory_mib', 'used_memory_mib'],
               'csv_rows': observation.splitlines(), 'neural_probe_gpu_use': False}
    except (OSError, subprocess.SubprocessError):
        gpu = {'observed_at': utc(), 'source': 'nvidia-smi-unavailable', 'neural_probe_gpu_use': False}
    report = {'schema_version': 'neural-train-only-resource-result-v1', 'registration_sha256': file_hash(output/'registration.json'),
              'torch_version': _torch().__version__, 'cuda_build': _torch().version.cuda,
              'python_version': platform.python_version(), 'platform': platform.platform(),
              'device': 'cpu', 'threads': config['threads'], 'summary': bundle['training_summary'],
              'peak_process_rss_mib': rss, 'restore_exact': restore_exact,
              'fit_seconds_within_limit': bundle['training_summary']['train_seconds'] <= max_seconds,
              'rss_within_limit': rss <= max_rss_mib,
              'inference_probe_examples': len(texts), 'inference_probe_partition': 'TRAIN',
              'inference_probe_seconds': inference_seconds, 'save_restore_seconds': save_restore_seconds,
              'gpu_observation': gpu,
              'dev_examples_observed': 0, 'test_examples_observed': 0,
              'identity': neural_identity(bundle)}
    report['passed'] = restore_exact and report['fit_seconds_within_limit'] and report['rss_within_limit']
    write_json(output/'report.json', report)
    if not report['passed']:
        raise ValueError('NEURAL_RESOURCE_GATE_FAILED_NO_AUTOMATIC_EXPANSION')
    return report


def main():
    import argparse
    import json
    from .clinc import audit_clinc, fetch_clinc
    from .runner import ROOT
    parser = argparse.ArgumentParser(description='One fixed CLINC TRAIN-only neural resource probe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = ROOT/'datasets/clinc150-828f8093932c'
    source = fetch_clinc(directory)
    data = audit_clinc(json.loads((directory/'data_full.json').read_text()), source=source)
    result = resource_probe(data['train'], args.output)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
