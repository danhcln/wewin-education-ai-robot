"""Summarize sampled Windows measurements; never opens the production DB."""
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.benchmark_resources import percentile,save


def stats(values):
    return {'mean':statistics.mean(values),'p95':percentile(values,.95),'peak':max(values)} if values else None


def analyze(directory):
    directory=Path(directory);run=directory/'full'
    samples=[json.loads(line) for line in (run/'samples.jsonl').read_text().splitlines()]
    phases=json.loads((run/'phases.json').read_text())
    output={}
    for phase in phases:
        rows=[r for r in samples if phase['start']<=r['t']<=phase['end']]
        if not rows:continue
        roles={}
        for role in ('api','bridge','sql','sync'):
            active=[r['roles'][role] for r in rows if r['roles'].get(role,{}).get('processes',0)]
            if active:roles[role]={key:stats([r[key] for r in active]) for key in ('rss_bytes','private_bytes','cpu_pct_one_core')}
        totals={}
        for key in ('rss_bytes','private_bytes','cpu_pct_one_core'):
            totals[key]=stats([sum(v[key] for role,v in row['roles'].items() if role in ('api','bridge','sync')) for row in rows])
        logs={key:rows[-1]['sizes'].get(key,0)-rows[0]['sizes'].get(key,0) for key in ('api/stdout.log','bridge/stdout.log','api/logs/connector.log','bridge/logs/connector.log')}
        output[phase['name']]={**phase,'samples':len(rows),'roles':roles,'runtime_totals':totals,
                              'host_cpu_pct':stats([r['host_cpu_pct'] for r in rows]),
                              'wal_sampled_peak_bytes':max(r['sizes'].get('db-wal',0) for r in rows),
                              'log_sample_delta_bytes':logs}
    soak=output['mcp_soak_10'];rows=[r for r in samples if soak['start']+60<=r['t']<=soak['end']]
    def memory(row):return sum(row['roles'][k]['private_bytes'] for k in ('api','bridge'))/1048576
    xs=[r['t'] for r in rows];ys=[memory(r) for r in rows];mx=statistics.mean(xs);my=statistics.mean(ys)
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs)*60
    first=[memory(r) for r in samples if soak['start']<=r['t']<soak['start']+60]
    last=[memory(r) for r in samples if soak['end']-60<r['t']<=soak['end']]
    trend={'seconds':soak['duration'],'samples':len(rows),'private_mib_per_minute_after_first_minute':slope,
           'first_minute_mean_private_mib':statistics.mean(first),'last_minute_mean_private_mib':statistics.mean(last),
           'delta_mib':statistics.mean(last)-statistics.mean(first),'not_a_long_term_leak_proof':True}
    build_samples=[json.loads(x) for x in (directory/'frontend-build/samples.jsonl').read_text().splitlines()]
    build_rows=[r['roles']['frontend_build'] for r in build_samples if r['roles'].get('frontend_build',{}).get('processes')]
    build={key:stats([r[key] for r in build_rows]) for key in ('rss_bytes','private_bytes','cpu_pct_one_core')}
    summary={'phases':output,'soak_trend':trend,'frontend_build':build,
             'sample_interval_actual_seconds':stats([b['t']-a['t'] for a,b in zip(samples,samples[1:])]),
             'windows_process_tree_includes_conhost':True,'cpu_100pct_is_one_logical_cpu':True,
             'sampling_peak_not_instantaneous_peak':True}
    save(directory/'aggregated_metrics.json',summary)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':9})
    fig,axes=plt.subplots(2,1,figsize=(14,8),sharex=True)
    ts=[r['t']/60 for r in samples]
    for role,color in [('api','#2563eb'),('bridge','#e8590c'),('sync','#16a34a')]:
        axes[0].plot(ts,[r['roles'].get(role,{}).get('private_bytes',0)/1048576 for r in samples],label=role,color=color,lw=1)
        axes[1].plot(ts,[r['roles'].get(role,{}).get('cpu_pct_one_core',0) for r in samples],label=role,color=color,lw=.8,alpha=.8)
    for p in phases:
        axes[0].axvline(p['start']/60,color='#999',lw=.4,alpha=.5)
        axes[1].axvline(p['start']/60,color='#999',lw=.4,alpha=.5)
        label=p['name'].replace('mcp_','').replace('gui_static_transfer','GUI').replace('sync_fixture_with_10_clients','sync + 10').replace('_',' ')
        axes[0].text((p['start']+p['end'])/120,1.02,label,rotation=65,ha='left',fontsize=6,transform=axes[0].get_xaxis_transform())
    axes[0].set_ylabel('Private memory, MiB');axes[0].legend(loc='upper left')
    axes[1].set_ylabel('CPU % (100 = one logical CPU)');axes[1].set_xlabel('Elapsed minutes')
    axes[1].axhline(100,color='black',ls='--',lw=.7)
    for ax in axes:ax.grid(alpha=.18)
    fig.suptitle('WeWIN: measured Windows process trees, 0.5 s sampling target',y=.995)
    fig.tight_layout(rect=(0,0,1,.96));fig.savefig(ROOT/'PHASE6B2A_RESOURCES.png',dpi=170);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for ax,prefix,title in [(axes[0],'mcp_paced_','MCP: one request / 5 s / client'),(axes[1],'api_burst_','HTTP API: closed-loop stress')]:
        ns=[1,5,10];width=.35
        for offset,key,label,color in [(-width/2,'latency_p50_ms','P50','#2563eb'),(width/2,'latency_p95_ms','P95','#e8590c')]:
            ax.bar([i+offset for i in range(3)],[output[prefix+str(n)][key] for n in ns],width,label=label,color=color)
        ax.set_xticks(range(3),[str(n) for n in ns]);ax.set_xlabel('Concurrent clients');ax.set_ylabel('Latency, ms');ax.set_title(title);ax.grid(axis='y',alpha=.2);ax.legend()
    fig.tight_layout();fig.savefig(ROOT/'PHASE6B2A_LATENCY.png',dpi=170);plt.close(fig)
    print(json.dumps({'soak_trend':trend,'phases':{k:{'private_mib':v['runtime_totals']['private_bytes']['peak']/1048576,'rss_mib':v['runtime_totals']['rss_bytes']['peak']/1048576,'cpu_mean':v['runtime_totals']['cpu_pct_one_core']['mean'],'cpu_peak':v['runtime_totals']['cpu_pct_one_core']['peak'],'wal_peak':v['wal_sampled_peak_bytes']} for k,v in output.items()},'frontend_build':build}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True,type=Path)
    analyze(parser.parse_args().directory)
