import json
import glob
from collections import defaultdict
import statistics

files = [
    "data/history/1776981064838.json",
    "data/history/1777335375296.json",
    "data/history/1777338750649.json",
    "data/history/1778577249439.json"
]

print("# Pipeline History Evaluation Report\n")

for filepath in files:
    with open(filepath, 'r') as f:
        d = json.load(f)
    
    timestamp = d.get('timestamp')
    events = d.get('events', [])
    
    complete_events = [e for e in events if e.get('event') == 'pipeline_complete']
    if not complete_events:
        continue
    stats = complete_events[0]['data']
    
    nodes = [e for e in events if e.get('event') == 'node_complete']
    
    stage_stats = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "gate_a": [], "gate_b": [], "failures": []})
    
    for n in nodes:
        nd = n.get('data', {})
        stage = nd.get('stage', 'unknown')
        stage_stats[stage]["total"] += 1
        
        gate_a = nd.get('gate_a_score', 0)
        gate_b = nd.get('gate_b_score', 0)
        if gate_a is not None: stage_stats[stage]["gate_a"].append(gate_a)
        if gate_b is not None: stage_stats[stage]["gate_b"].append(gate_b)
        
        if nd.get('passed'):
            stage_stats[stage]["passed"] += 1
        else:
            stage_stats[stage]["failed"] += 1
            if 'critic_feedback' in nd:
                issues = nd['critic_feedback'].get('issues', [])
                missing = nd['critic_feedback'].get('missing_elements', [])
                stage_stats[stage]["failures"].append({"issues": issues, "missing": missing})
            
    print(f"## Run: {timestamp} (ID: {d.get('id')})")
    print(f"- **Duration**: {stats.get('duration_ms')/1000:.1f}s")
    print(f"- **Overall Pass Rate**: {stats.get('gates_passed')}/{stats.get('gates_total')} ({(stats.get('gates_passed', 0)/max(1, stats.get('gates_total', 1)))*100:.1f}%)")
    print(f"- **Avg Gate A**: {stats.get('avg_gate_a'):.3f} | **Avg Gate B**: {stats.get('avg_gate_b'):.1f}")
    
    print("\n### Stage Breakdown")
    print("| Stage | Total | Passed | Failed | Pass % | Avg Gate A | Avg Gate B |")
    print("|-------|-------|--------|--------|--------|------------|------------|")
    for stage, s in stage_stats.items():
        pass_pct = (s['passed']/s['total'])*100 if s['total'] > 0 else 0
        avg_a = statistics.mean(s['gate_a']) if s['gate_a'] else 0
        avg_b = statistics.mean(s['gate_b']) if s['gate_b'] else 0
        print(f"| {stage} | {s['total']} | {s['passed']} | {s['failed']} | {pass_pct:.1f}% | {avg_a:.3f} | {avg_b:.1f} |")
        
    print("\n### Common Failure Reasons")
    has_failures = False
    for stage, s in stage_stats.items():
        if s['failures']:
            has_failures = True
            print(f"**{stage} Failures:**")
            for idx, f in enumerate(s['failures']):
                issues = ", ".join(f['issues']) if f['issues'] else "None"
                missing = ", ".join(f['missing']) if f['missing'] else "None"
                if len(issues) > 100: issues = issues[:100] + "..."
                if len(missing) > 100: missing = missing[:100] + "..."
                print(f"- Issues: {issues} | Missing: {missing}")
    if not has_failures:
        print("*No failures in this run.*")
    print("\n---\n")

