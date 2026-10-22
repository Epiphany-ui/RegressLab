const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const base=path.resolve(__dirname,'..');
const specs=path.join(base,'docs','specs');
const contracts=path.join(base,'docs','contracts');
const records=path.join(base,'docs','verification');
const results=[];
function check(name,fn){try{fn();results.push({name,status:'PASS'});}catch(e){results.push({name,status:'FAIL',detail:e.message});}}
function assert(x,m){if(!x)throw Error(m);}
const excludedDirs=new Set(['.git','.cache','.venv','node_modules','dist','var','.pytest_cache','__pycache__','test-results','playwright-report']);
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?(excludedDirs.has(e.name)?[]:files(path.join(dir,e.name))):[path.join(dir,e.name)]);}
const load=f=>JSON.parse(fs.readFileSync(path.join(contracts,f),'utf8'));
const api=load('openapi.json');
function pointer(root,ref){assert(ref.startsWith('#/'),'non-local reference '+ref);return ref.slice(2).split('/').reduce((o,k)=>{k=k.replaceAll('~1','/').replaceAll('~0','~');assert(o&&Object.hasOwn(o,k),'unresolved '+ref);return o[k];},root);}
function walk(x,fn){if(x&&typeof x==='object'){fn(x);Object.values(x).forEach(v=>walk(v,fn));}}
function validate(schema,value,root,at='$'){
 if(schema===true)return;
 if(schema===false)throw Error(at+' forbidden');
 if(schema.allOf)for(const sub of schema.allOf)validate(sub,value,root,at);
 if(schema.if){let matches=true;try{validate(schema.if,value,root,at);}catch{matches=false;}if(matches&&schema.then)validate(schema.then,value,root,at);if(!matches&&schema.else)validate(schema.else,value,root,at);}
 if(schema.not){let matches=true;try{validate(schema.not,value,root,at);}catch{matches=false;}assert(!matches,at+' forbidden not match');}
 if(schema.$ref)return validate(pointer(root,schema.$ref),value,root,at);
 if(schema.oneOf){let n=0;for(const s of schema.oneOf){try{validate(s,value,root,at);n++;}catch{}}assert(n===1,at+' oneOf matches='+n);}
 if(schema.anyOf){let n=0;for(const s of schema.anyOf){try{validate(s,value,root,at);n++;}catch{}}assert(n>0,at+' anyOf mismatch');}
 if(Object.hasOwn(schema,'const'))assert(JSON.stringify(value)===JSON.stringify(schema.const),at+' const mismatch');
 if(schema.enum)assert(schema.enum.some(v=>JSON.stringify(v)===JSON.stringify(value)),at+' enum mismatch');
 const type=value===null?'null':Array.isArray(value)?'array':typeof value;
 if(schema.type){const types=Array.isArray(schema.type)?schema.type:[schema.type];assert(types.includes(type)||(types.includes('integer')&&type==='number'&&Number.isInteger(value)),at+' type '+type);}
 if(type==='object'){
  for(const key of schema.required||[])assert(Object.hasOwn(value,key),at+' missing '+key);
  if(schema.additionalProperties===false)for(const key of Object.keys(value))assert(schema.properties&&Object.hasOwn(schema.properties,key),at+' unknown '+key);
  for(const [key,s] of Object.entries(schema.properties||{}))if(Object.hasOwn(value,key))validate(s,value[key],root,at+'.'+key);
 }
 if(type==='array'){
  if(schema.minItems!==undefined)assert(value.length>=schema.minItems,at+' too short');
  if(schema.maxItems!==undefined)assert(value.length<=schema.maxItems,at+' too long');
  value.forEach((x,i)=>{const s=(schema.prefixItems||[])[i]||schema.items;if(s!==undefined)validate(s,x,root,at+'['+i+']');});
 }
 if(type==='string'){
  if(schema.minLength!==undefined)assert(Array.from(value).length>=schema.minLength,at+' short string');
  if(schema.maxLength!==undefined)assert(Array.from(value).length<=schema.maxLength,at+' long string');
  if(schema.pattern)assert(new RegExp(schema.pattern).test(value),at+' pattern');
  if(schema.format==='uuid')assert(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value),at+' uuid');
  if(schema.format==='date-time')assert(!Number.isNaN(Date.parse(value)),at+' datetime');
 }
 if(type==='number'){
  assert(Number.isFinite(value),at+' nonfinite');
  if(schema.minimum!==undefined)assert(value>=schema.minimum,at+' minimum');
  if(schema.maximum!==undefined)assert(value<=schema.maximum,at+' maximum');
 }
}
check('All JSON files parse and local schema references resolve',()=>{for(const f of files(base).filter(f=>f.endsWith('.json'))){const doc=JSON.parse(fs.readFileSync(f,'utf8'));walk(doc,s=>{if(s.$ref)pointer(doc,s.$ref);if(s.required&&s.properties)for(const k of s.required)assert(Object.hasOwn(s.properties,k),'required property missing in '+f);});}});
check('OpenAPI operation IDs/path parameters/idempotency headers',()=>{
 assert(api.openapi==='3.1.0','OpenAPI version');const ids=new Set();
 for(const [p,methods] of Object.entries(api.paths))for(const [m,o] of Object.entries(methods)){
  assert(!ids.has(o.operationId),'duplicate operationId');ids.add(o.operationId);
  for(const match of p.matchAll(/\{(\w+)\}/g))assert(o.parameters.some(q=>q.in==='path'&&q.name===match[1]&&q.required),'missing path param '+p);
  if(m==='post')assert(o.parameters.some(q=>q.in==='header'&&q.name==='Idempotency-Key'&&q.required),'missing idempotency '+p);
 }
 for(const p of ['/projects/{project_id}/suites','/suites/{suite_id}/replays','/analyses/{analysis_id}/confusions','/suites/{suite_id}/inputs'])assert(api.paths[p]?.get,'missing required route '+p);
});
check('Default production configuration and valid examples',()=>{
 validate(api.components.schemas.AnalysisConfig,load('default-analysis-config.json'),api);
 validate(api.components.schemas.AnalysisCreate,load('examples/analysis-request.json'),api);
 for(const [s,x] of [['input-sample','input-sample'],['prediction-row','prediction-row'],['report','report']]){const schema=load(s+'.schema.json');validate(schema,load('examples/'+x+'.json'),schema);}
 validate(api.components.schemas.BuiltinConfig,{ngram_range:[2,4],C:1,train_fraction:1,seed:42},api);
});
check('Schemas reject illegal fields, labels shape, ranges and changed protocol',()=>{
 const bad=[['InputSample',{...load('examples/input-sample.json'),role:'AUDIT'}],['PredictionRow',{sample_id:'x',prediction_label:'A',gold_label:'A'}],['BuiltinConfig',{ngram_range:[1,4],C:1,train_fraction:1,seed:42}],['AnalysisConfig',{...load('default-analysis-config.json'),alpha:0.2}]];
 for(const [n,v]of bad){let failed=false;try{validate(api.components.schemas[n],v,api);}catch{failed=true;}assert(failed,'bad '+n+' accepted');}
});
check('Paired fixture arithmetic and independent exact binomial tail',()=>{
 const rows=fs.readFileSync(path.join(contracts,'fixtures/paired-cases.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse);
 const e=load('fixtures/paired-expected.json');const c={a:0,b:0,c:0,d:0};
 for(const r of rows){const a=r.old_prediction_label===r.gold_label,b=r.new_prediction_label===r.gold_label;c[a?(b?'a':'b'):(b?'c':'d')]++;}
 for(const k of ['a','b','c','d'])assert(c[k]===e[k],'count '+k);
 const n=rows.length;const derived={n,old_accuracy:(c.a+c.b)/n,new_accuracy:(c.a+c.c)/n,accuracy_drop:(c.b-c.c)/n,negative_flip_rate:c.b/n,positive_flip_rate:c.c/n,old_correct_regression_rate:c.b/(c.a+c.b)};
 for(const[k,v]of Object.entries(derived))assert(Math.abs(v-e[k])<1e-12,'metric '+k);
 const total=c.b+c.c;let tail=0;for(let k=c.b;k<=total;k++){let choose=1;for(let j=1;j<=k;j++)choose=choose*(total-j+1)/j;tail+=choose/2**total;}
 assert(Math.abs(tail-e.exact_one_sided_p)<1e-12,'exact tail');
 const report=load('examples/report.json');for(const[k,v]of Object.entries(derived))assert(Math.abs(report.metrics.discovery[k]-v)<1e-12,'report '+k);
 for(const cell of report.confusion_changes.cells)assert(cell.delta===cell.new_count-cell.old_count,'confusion delta');
});
check('Coverage selection fixture and Holm worked example',()=>{
 const f=load('fixtures/selection-fixture.json');const covered=new Set(),selected=[];
 for(let t=0;t<f.budget;t++){
  const ranked=f.items.filter(x=>!selected.includes(x.sample_id)).map(x=>({x,score:1000*f.obligations.filter(o=>x.covers.includes(o.id)&&!covered.has(o.id)).reduce((n,o)=>n+o.weight,0)+10*Number(x.historical_negative_flip)+x.diversity})).sort((a,b)=>b.score-a.score||a.x.sample_id.localeCompare(b.x.sample_id));
  selected.push(ranked[0].x.sample_id);ranked[0].x.covers.forEach(x=>covered.add(x));
 }
 assert(JSON.stringify(selected)===JSON.stringify(f.expected_ids),'selection order');
 const ps=[.001,.03,.04],adj=[];for(let i=0;i<ps.length;i++)adj.push(Math.min(1,Math.max(i?adj[i-1]:0,(ps.length-i)*ps[i])));
 [.003,.06,.06].forEach((x,i)=>assert(Math.abs(x-adj[i])<1e-12,'Holm'));
});
check('DDL structural references, balanced syntax and review constraints',()=>{
 const sql=fs.readFileSync(path.join(contracts,'schema.sql'),'utf8');const tables=new Set(Array.from(sql.matchAll(/CREATE TABLE (\w+)/g),m=>m[1]));assert(tables.size===17,'table count '+tables.size);
 for(const m of sql.matchAll(/REFERENCES (\w+)\(/g))assert(tables.has(m[1]),'unknown table '+m[1]);
 const stripped=sql.replace(/--[^\n]*/g,'').replace(/'(?:''|[^'])*'/g,"''");let depth=0;for(const ch of stripped){if(ch==='(')depth++;if(ch===')')depth--;assert(depth>=0,'closing parentheses');}assert(depth===0,'unbalanced parentheses');
 assert(sql.includes('judge_enqueued BOOLEAN'),'missing replay fence');assert(sql.includes('jobs_one_active_kind_resource'),'missing active job uniqueness');assert(sql.includes('UNIQUE(evaluation_data_sha256,old_model_content_hash,new_model_content_hash)'),'missing C-use uniqueness');
});
check('Internal Markdown links resolve and no unresolved planning markers',()=>{
 for(const f of files(base).filter(x=>x.endsWith('.md'))){
  const text=fs.readFileSync(f,'utf8');for(const m of text.matchAll(/\]\(([^)]+)\)/g)){
   let target=m[1].split('#')[0];if(!target||/^(https?:|mailto:)/.test(target))continue;target=target.replace(/^<|>$/g,'');assert(fs.existsSync(path.resolve(path.dirname(f),target)),'missing '+path.relative(base,f)+' → '+target);
  }
  assert(!/\bTODO\b|\bTBD\b/.test(text.replace('不出现未决定业务项TBD','')),'unresolved marker '+path.basename(f));
 }
});
check('Experiment method registry and documented development/final gates agree',()=>{
 const d=load('selection-experiment-design.json');
 const required=['random','stratified','historical','coverage','diversity','complete','ablate_history','ablate_diversity'];
 assert(d.methods.length===9,'method count');
 assert(JSON.stringify(d.methods.filter(m=>m.required).map(m=>m.id))===JSON.stringify(required),'required methods');
 assert(d.methods.filter(m=>m.kind==='baseline').length===5,'five baselines');
 assert(d.methods.find(m=>m.id==='history_first')?.required===false,'optional priority control');
 assert(d.production.changed_in_this_revision===false&&d.production.algorithm==='coverage_diversity_v1','production drift');
 assert(d.development.max_rounds===2&&d.development.future_model_content_hashes_disjoint_from_final,'development boundary');
 assert(d.final.freeze_before_formal_confirmation_and_future_predictions&&d.final.all_methods_share_one_confirmation_union,'final boundary');
 assert(d.promotion_gate.min_valid_chains===3&&d.promotion_gate.min_macro_group_recall_gain===.05,'promotion gate');
 const text=fs.readFileSync(path.join(specs,'17-baselines-and-algorithm-evolution.md'),'utf8');
 for(const m of d.methods)assert(text.includes(m.id),'undocumented method '+m.id);
 const tests=fs.readFileSync(path.join(specs,'09-test-plan.md'),'utf8');
 for(let i=37;i<=44;i++)assert(tests.includes('TC-'+i),'missing planned test '+i);
});
check('Independent baseline fixture calculations and ablation invariance',()=>{
 const f=load('fixtures/selection-baselines.json');
 const idcmp=(a,b)=>Buffer.compare(Buffer.from(a),Buffer.from(b));
 const rng=id=>crypto.createHash('sha256').update('baseline-rng-v1|'+f.seed+'|'+id,'utf8').digest('hex');
 const randcmp=(a,b)=>idcmp(rng(a.sample_id),rng(b.sample_id))||idcmp(a.sample_id,b.sample_id);
 const random=f.items.slice().sort(randcmp);
 const eq=(a,b,n)=>assert(JSON.stringify(a)===JSON.stringify(b),'fixture '+n);
 eq(random.map(x=>x.sample_id),f.expected.seeded_order,'seed order');
 eq(random.slice(0,f.budget).map(x=>x.sample_id),f.expected.random,'random');
 eq(f.items.slice().sort((a,b)=>b.historical_flip-a.historical_flip||randcmp(a,b)).slice(0,f.budget).map(x=>x.sample_id),f.expected.historical,'historical');
 const labels=[...new Set(f.items.map(x=>x.gold_label))].sort(idcmp),quotas={},remainders=[];
 for(const label of labels){const share=f.budget*f.items.filter(x=>x.gold_label===label).length/f.items.length;quotas[label]=Math.floor(share);remainders.push({label,part:share-Math.floor(share)});}
 remainders.sort((a,b)=>b.part-a.part||idcmp(a.label,b.label));
 const extra=f.budget-Object.values(quotas).reduce((s,x)=>s+x,0);for(let i=0;i<extra;i++)quotas[remainders[i].label]++;
 eq(quotas,f.expected.stratified_quotas,'stratified quotas');
 eq(labels.flatMap(l=>random.filter(x=>x.gold_label===l).slice(0,quotas[l])).sort(randcmp).map(x=>x.sample_id),f.expected.stratified,'stratified');
 function select(method,items=f.items){
  const selected=[],covered=new Set(),weights=Object.fromEntries(f.obligations.map(x=>[x.id,x.weight]));
  const dist=(a,b)=>{const na=Math.hypot(...a.vector),nb=Math.hypot(...b.vector);if(!na&&!nb)return 0;if(!na||!nb)return 1;return Math.max(0,Math.min(1,1-a.vector.reduce((s,x,i)=>s+x*b.vector[i],0)/(na*nb)));};
  const compare=(a,b)=>{for(let i=0;i<a.length;i++){if(Math.abs(a[i]-b[i])>1e-12)return b[i]-a[i];}return 0;};
  while(selected.length<Math.min(f.budget,items.length)){
   const candidates=items.filter(x=>!selected.some(s=>s.sample_id===x.sample_id)).map(x=>{
    const gain=x.covers.filter(t=>!covered.has(t)).reduce((s,t)=>s+weights[t],0),H=x.historical_flip,D=selected.length?Math.min(...selected.map(s=>dist(x,s))):1;
    const key=method==='complete'?[gain,H,D]:method==='coverage'?[gain]:method==='diversity'?[D]:method==='ablate_history'?[gain,D]:method==='ablate_diversity'?[gain,H]:[H,gain,D];
    return {x,key};
   });
   candidates.sort((a,b)=>compare(a.key,b.key)||((method==='coverage'||(method==='diversity'&&!selected.length))?randcmp(a.x,b.x):idcmp(a.x.sample_id,b.x.sample_id)));
   selected.push(candidates[0].x);candidates[0].x.covers.forEach(t=>covered.add(t));
  }
  return selected.map(x=>x.sample_id);
 }
 for(const m of ['coverage','diversity','complete','ablate_history','ablate_diversity','history_first'])eq(select(m),f.expected[m],m);
 eq(select('ablate_history',f.items.map(x=>({...x,historical_flip:1-x.historical_flip}))),f.expected.ablate_history,'H removed');
 eq(select('ablate_diversity',f.items.map(x=>({...x,vector:[0,1]}))),f.expected.ablate_diversity,'D removed');
 for(const m of ['complete','coverage','diversity','history_first'])assert(new Set(select(m)).size===f.budget,'duplicates '+m);
});
check('Integer coverage score is equivalent to explicit lexicographic priority',()=>{
 const rows=[];for(let gain=0;gain<=4;gain++)for(const H of [0,1])for(const D of [0,.3,1])rows.push([gain,H,D]);
 for(const a of rows)for(const b of rows){const score=Math.sign(1000*(a[0]-b[0])+10*(a[1]-b[1])+a[2]-b[2]);let lex=0;for(let i=0;i<3;i++)if(a[i]!==b[i]){lex=Math.sign(a[i]-b[i]);break;}assert(score===lex,'priority mismatch');}
});

check('v1.3 adapters and immutable identity contracts',()=>{
 const S=api.components.schemas;
 assert(S.ModelCreate.oneOf.length===3,'three model kinds');
 assert(api.paths['/runtime/ollama/models']?.get,'Ollama inventory');
 assert(api.paths['/projects/{project_id}/models/ollama-check']?.post,'Ollama inspection');
 for(const k of ['weights_sha256','inference_config_sha256','provenance_sha256','provenance_status','parent_model_version_id','change_type'])assert(S.ModelVersion.properties[k],'model identity '+k);
 for(const k of ['run_id','raw_response'])assert(S.PredictionRow.required.includes(k),'prediction '+k);
 assert(S.PredictionRow.properties.raw_response.minLength===1,'empty raw response');
 assert(S.InferenceIdentity.required.includes('parser_version'),'parser identity');
 for(const n of ['Report','SuiteExport'])assert(S[n].properties.schema_version.const==='1.1','export schema '+n);
 const registry=load('selection-experiment-design.json');
 assert(JSON.stringify(registry.model_protocol.application_content_fields)===JSON.stringify(['labelset_sha256','weights_sha256','inference_config_sha256']),'behavioral app fingerprint');
 assert(registry.model_protocol.excluded_metadata_from_application_identity.includes('kind'),'kind cannot reset C');
 const text=fs.readFileSync(path.join(specs,'03-data-protocol.md'),'utf8');assert(text.includes('kind、名称、provenance和run_id不进入该身份'),'identity prose');
});
check('v1.3 conditional local weight provenance shape rejects fabricated missing identity',()=>{
 const z='0'.repeat(64),inference={backend:'fixture',backend_version:'1',tokenizer_revision:'fixture',prompt_sha256:z,label_contract_sha256:z,precision:'float16',decoding:{method:'GREEDY_LABEL_TRIE',temperature:0,seed:42,max_context_tokens:1024,max_output_tokens:64},runtime_environment_sha256:z,parser_version:'label-json-v1'};
 const p={source_model_id:'fixture',source_revision:'UNKNOWN_PROVIDER_REVISION',weights_manifest:[],weights_sha256:null,inference,inference_config_sha256:z,training:null,source_type:'API_SERVICE'};
 validate(api.components.schemas.ModelProvenance,p,api);
 for(const source_type of ['PUBLIC_WEIGHTS','LOCAL_CHECKPOINT']){let rejected=false;try{validate(api.components.schemas.ModelProvenance,{...p,source_type},api);}catch{rejected=true;}assert(rejected,'missing local weights accepted '+source_type);}
 let rejected=false;try{validate(api.components.schemas.PredictionRow,{...load('examples/prediction-row.json'),raw_response:''},api);}catch{rejected=true;}assert(rejected,'empty raw accepted');
});
check('v1.3 evidence modes and complete prediction boundary',()=>{
 const S=api.components.schemas;
 assert(S.AnalysisCreate.required.includes('evidence_mode')&&S.AnalysisCreate.required.includes('stability_report'),'analysis evidence required');
 const x=load('examples/report.json');assert(x.fixture===true&&x.evidence_mode==='DESCRIPTIVE_ONLY','fixture must not imply real confirmation');
 assert(x.metrics.confirmation===null,'descriptive C null');
 const d=load('selection-experiment-design.json');assert(d.stability_gate.dev_sample_count===100&&d.stability_gate.repeated_runs_per_version===3,'stability size');
 assert(d.stability_gate.fewer_than_100_dev_samples==='LLM_CONFIRMATORY_NOT_ALLOWED','small pilot not confirmation');
 assert(d.stability_gate.repeats_are_independent_samples===false,'noise pseudoreplication');
 const protocol=fs.readFileSync(path.join(specs,'19-model-version-protocol.md'),'utf8');assert(protocol.includes('v3的DEV稳定性推理也必须等全部selector套件冻结后'),'future stability leakage');
});
check('v1.3 lab AUDIT and common-pool execution path is separate and frozen',()=>{
 const d=load('selection-experiment-design.json'),lab=load('lab-prediction-run.schema.json');
 assert(d.lab_prediction.product_HTTP_import_allowed===false&&d.lab_prediction.product_HTTP_AUDIT_access===false,'no hidden-role HTTP access');
 assert(d.lab_prediction.future_export_requires_all_suites_frozen,'future before suite freeze');
 assert(lab.properties.product_import_allowed.const===false,'lab manifest not product');
 assert(lab.required.includes('all_suites_freeze_sha256')&&lab.required.includes('evaluation_data_sha256'),'lab identities');
 assert(d.lab_prediction.inference_command.includes('regresslab_experiments.cli'),'one executable planned module');
 for(const f of ['11-experiment-protocol.md','12-implementation-plan.md','19-model-version-protocol.md'])assert(fs.readFileSync(path.join(specs,f),'utf8').includes('lab prediction-inputs'),'lab CLI '+f);
});
check('v1.3 tuple implementation preserves tiny diversity tie-breaks',()=>{
 const d=Number.EPSILON;assert(1000+d===1000,'fixture must expose scalar float loss');
 const first=[1,0,d],second=[1,0,0];let direct=0;for(let i=0;i<3;i++)if(first[i]!==second[i]){direct=Math.sign(first[i]-second[i]);break;}
 assert(direct===1,'tuple retains diversity distinction');
 const cfg=load('selection-experiment-design.json');assert(cfg.production.implementation_ordering.includes('compare_tuple'),'real comparator');
});
check('v1.3 root scope and test traceability have no inherited contradictions',()=>{
 for(const f of ['PRODUCT.md','README.md','00-project-charter.md','16-proposal-summary.md']){
  const text=fs.readFileSync(path.join(f==='README.md'?base:specs,f),'utf8');assert(text.includes('微调')&&text.includes('逻辑回归'),'main and control '+f);assert(!/Laptop|6GB.*笔记本/.test(text),'hardware '+f);
 }
 const tests=fs.readFileSync(path.join(specs,'09-test-plan.md'),'utf8');for(let n=45;n<=62;n++)assert(tests.includes('TC-'+n),'new test '+n);
 const sources=fs.readFileSync(path.join(specs,'15-sources-decisions.md'),'utf8'),ids=Array.from(sources.matchAll(/^\| (S\d+) \|[^\n]*https?:/gm),m=>m[1]);assert(ids.length===new Set(ids).size,'duplicate source definition IDs');
 for(const f of files(base).filter(x=>x.endsWith('.md'))){const text=fs.readFileSync(f,'utf8');for(const m of text.matchAll(/\[(S\d+)\]/g))assert(ids.includes(m[1]),'missing source '+m[1]+' '+f);}
});

const failures=results.filter(r=>r.status==='FAIL');
const report={generated_at:new Date().toISOString(),scope:'Document static checks only; custom validator covers used JSON Schema keywords, not a formal standards-certified validator. No application, external API, model training or PostgreSQL runtime validation was performed.',counts:{markdown_files:files(base).filter(f=>f.endsWith('.md')).length,openapi_paths:Object.keys(api.paths).length,openapi_operations:Object.values(api.paths).reduce((n,x)=>n+Object.keys(x).length,0),openapi_schemas:Object.keys(api.components.schemas).length},checks:results,status:failures.length?'FAIL':'PASS',not_executed:['PostgreSQL migration execution','SciPy/sklearn runtime cross-checks','actual MASSIVE download and model runs','application API/UI/worker tests','research effect experiments']};
fs.mkdirSync(records,{recursive:true});fs.writeFileSync(path.join(records,'static-checks.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));if(failures.length)process.exitCode=1;
