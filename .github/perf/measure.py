import ast,json,os,re,resource,shutil,statistics,subprocess,sys,time
from pathlib import Path
wd=Path(sys.argv[1]).resolve(); case=sys.argv[2]; results=Path('results').resolve(); results.mkdir()
file,test={'linear':('texture.rs','texture::tests::contiguous_linear_copy_throughput'),'peek':('xma.rs','xma::tests::perf_peek32'),'vlc':('xma.rs','xma::tests::perf_vlc'),'frame':('xma.rs','xma::tests::perf_frame_gather'),'overlap':('xma.rs','xma::tests::perf_overlap')}[case]
src=Path('crates/victory-formats/src')/file
patch=(wd/src).read_text(); base=subprocess.check_output(['git','show',f'a31fcca:{src}'],cwd=wd,text=True)
marker='#[cfg(test)]\nmod tests'; assert marker in patch and marker in base
baseline=base.split(marker)[0]+marker+patch.split(marker,1)[1]
metadata={'case':case,'base':subprocess.check_output(['git','rev-parse','a31fcca'],cwd=wd,text=True).strip(),'patch':subprocess.check_output(['git','rev-parse','HEAD'],cwd=wd,text=True).strip(),'kernel':subprocess.check_output(['uname','-a'],text=True),'cpu':subprocess.check_output(['lscpu'],text=True),'rust':subprocess.check_output(['rustc','-Vv'],cwd=wd,text=True),'test':test,'samples':[]}
# Same benchmark/regression tests; unchanged original production code for base.
# Independent target directories prevent stale cross-worktree artifacts.
for side,source in [('base',baseline),('patch',patch)]:
 (wd/src).write_text(source)
 env=dict(os.environ,CARGO_TARGET_DIR=str(wd/f'target-{side}'))
 build=subprocess.run(['cargo','test','-p','victory-formats','--release','--lib','--no-run','--message-format=json'],cwd=wd,env=env,text=True,capture_output=True)
 (results/f'{side}-build.log').write_text(build.stderr)
 if build.returncode: raise RuntimeError(build.stdout+build.stderr)
 artifacts=[json.loads(line) for line in build.stdout.splitlines()]
 binary=next(a['executable'] for a in artifacts if a.get('executable'))
 saved=results/f'{side}-tests'; shutil.copy2(binary,saved)
 check=subprocess.run([str(saved),'--test-threads=2'],text=True,capture_output=True)
 (results/f'{side}-tests.log').write_text(check.stdout+check.stderr)
 if check.returncode: raise RuntimeError(check.stdout+check.stderr)
# No compilation in timed samples; alternating AB/BA on one runner per pair.
for invocation in range(7):
 for side in (['base','patch'] if invocation%2==0 else ['patch','base']):
  before=resource.getrusage(resource.RUSAGE_CHILDREN); start=time.monotonic()
  run=subprocess.run([str(results/f'{side}-tests'),'--exact',test,'--ignored','--nocapture'],text=True,capture_output=True,check=True)
  wall=time.monotonic()-start; after=resource.getrusage(resource.RUSAGE_CHILDREN)
  (results/f'{side}-{invocation}.log').write_text(run.stdout+run.stderr)
  arrays={name:ast.literal_eval(values) for name,values in re.findall(r'(\w+_ns) (\[[0-9, ]+\])',run.stdout)}
  assert arrays and all(len(values)==31 for values in arrays.values())
  metadata['samples'].append({'side':side,'invocation':invocation,'wall_s':wall,'cpu_s':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,'metrics':{name:statistics.median(values) for name,values in arrays.items()}})
summary={}
for name in metadata['samples'][0]['metrics']:
 summary[name]={}
 for side in ['base','patch']:
  values=[s['metrics'][name] for s in metadata['samples'] if s['side']==side]
  summary[name][side]={'median_ns':statistics.median(values),'min_ns':min(values),'max_ns':max(values),'invocation_medians_ns':values}
 b,p=[summary[name][side]['median_ns'] for side in ['base','patch']]
 summary[name]['change_ns']=p-b; summary[name]['change_pct']=(p/b-1)*100
metadata['summary']=summary
(results/'results.json').write_text(json.dumps(metadata,indent=2)); print(json.dumps(metadata,indent=2))
# Upload numeric logs and metadata only, leaving executables on the runner.
for side in ['base','patch']: (results/f'{side}-tests').unlink()
