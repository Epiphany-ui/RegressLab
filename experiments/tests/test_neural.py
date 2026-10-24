"""TRAIN-only neural boundaries, deterministic inference and stored-state reuse."""
from copy import deepcopy

import numpy as np
import pytest

from preflight.neural import DEFAULT_NEURAL_CONFIG, build_vocabulary, fit_neural, load_neural, neural_identity, neural_probabilities, resource_probe, save_neural, tokenize


def rows():
    return [{'sample_id': f'train:{i}', 'role': 'TRAIN', 'text': text, 'gold_label': label} for i, (text,label) in enumerate([
        ('Book flight east', 'flight'), ('Book flight west', 'flight'), ('Cancel my flight', 'flight'),
        ('Play some music', 'music'), ('Play jazz music', 'music'), ('Stop my music', 'music'),
    ])]


def tiny_config():
    return {**DEFAULT_NEURAL_CONFIG, 'embedding_dim': 8, 'hidden_dim': 8, 'batch_size': 3, 'threads': 1}


def test_vocabulary_is_train_only_and_deterministically_tied():
    vocabulary = build_vocabulary(rows(), tiny_config())
    assert vocabulary == build_vocabulary(list(reversed(rows())), tiny_config())
    assert min(vocabulary.values()) == 2
    assert 'flight' in vocabulary
    assert tokenize('ＢＯＯＫ  flight?!') == ['book', 'flight', '?', '!']
    for role in ['DEV_SELECTOR', 'DEV_MODEL', 'TEST']:
        modified = rows();modified[0]['role'] = role
        with pytest.raises(ValueError, match='TRAIN_ONLY_REQUIRED'):
            build_vocabulary(modified, tiny_config())


@pytest.fixture
def fitted():
    pytest.importorskip('torch')
    sample = rows();config = tiny_config()
    return fit_neural(sample, build_vocabulary(sample,config), ['flight','music'], seed=5, epochs=2, config=config, max_seconds=30)


def test_neural_training_is_deterministic_and_restore_is_exact(fitted, tmp_path):
    config = tiny_config();sample = rows()
    again = fit_neural(sample, build_vocabulary(sample,config), ['flight','music'], seed=5, epochs=2, config=config, max_seconds=30)
    assert neural_identity(fitted) == neural_identity(again)
    probes = ['Book a flight', 'Unknown token', '']
    scores, labels = neural_probabilities(fitted, probes)
    assert scores.shape == (3,2) and np.allclose(scores.sum(axis=1),1,rtol=0,atol=1e-8)
    assert labels.tolist() == np.asarray(fitted['labels'])[scores.argmax(axis=1)].tolist()
    path = tmp_path/'neural.pt';save_neural(fitted,path)
    assert np.array_equal(neural_probabilities(load_neural(path),probes)[0],scores)
    assert neural_identity(fitted) == neural_identity(load_neural(path))
    with pytest.raises(FileExistsError):
        save_neural(fitted,path)


def test_fit_rejects_nontrain_rows_before_torch_or_training():
    sample = rows();vocabulary = build_vocabulary(sample,tiny_config());sample[0]['role'] = 'TEST'
    with pytest.raises(ValueError, match='TRAIN_ONLY_REQUIRED'):
        fit_neural(sample,vocabulary,['flight','music'],seed=5,epochs=2,config=tiny_config())


def test_identity_detects_weights_vocabulary_labels_and_ignores_training_metadata(fitted, monkeypatch):
    before = neural_identity(fitted)
    modified = deepcopy(fitted);modified['training_summary'] = {'unrelated': 100}
    modified['config']['learning_rate'] = 0.7
    assert neural_identity(modified) == before
    modified['state_dict']['hidden.bias'][0] += 1
    assert neural_identity(modified) != before
    modified = deepcopy(fitted);first, second = list(modified['vocabulary'])[:2]
    modified['vocabulary'][first],modified['vocabulary'][second] = modified['vocabulary'][second],modified['vocabulary'][first]
    assert neural_identity(modified) != before
    modified = deepcopy(fitted);modified['labels'] = list(reversed(modified['labels']))
    assert neural_identity(modified) != before
    def forbidden(*args,**kwargs):
        raise AssertionError('identity cannot predict or tokenize')
    monkeypatch.setattr('preflight.neural.tokenize',forbidden)
    assert neural_identity(fitted) == before
    assert first not in str(before['components']['vocabulary'])


def test_resource_probe_never_receives_dev_and_saves_only_train_probe(fitted, tmp_path):
    report = resource_probe(rows(),tmp_path/'probe',config=tiny_config(),fraction=0.5,epochs=1,max_seconds=30,max_rss_mib=4096)
    assert report['passed'] and report['restore_exact']
    assert report['dev_examples_observed'] == report['test_examples_observed'] == 0
    assert report['inference_probe_partition'] == 'TRAIN'


def test_empty_inference_has_valid_shape_and_preserves_rng(fitted):
    torch = pytest.importorskip('torch')
    state = torch.random.get_rng_state().clone()
    scores,labels = neural_probabilities(fitted,[])
    assert scores.shape == (0,2) and labels.shape == (0,)
    assert torch.equal(torch.random.get_rng_state(),state)
