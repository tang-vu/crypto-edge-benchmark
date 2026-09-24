"""
Benchmark Data Analysis Script

Analyzes k6 benchmark results and generates statistical summaries.
Outputs data suitable for academic paper inclusion.

Usage:
    python analyze.py [--input-dir benchmark/results] [--output-dir benchmark/analysis/output]
"""

import json
import os
import glob
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np
from scipy import stats
from tabulate import tabulate


def load_benchmark_results(input_dir: str) -> Dict[str, List[Dict]]:
    """Load all benchmark result JSON files from input directory."""
    results = {
        'cold-start': [],
        'warm-performance': [],
        'load-test': [],
        'burst-test': []
    }
    
    json_files = glob.glob(os.path.join(input_dir, '*.json'))
    
    for file_path in json_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            filename = os.path.basename(file_path)
            
            # Determine scenario type
            for scenario in results.keys():
                if scenario in filename:
                    # Extract platform from filename
                    platform = 'cloudflare' if 'cloudflare' in filename else 'lambda' if 'lambda' in filename else 'unknown'
                    data['_platform'] = platform
                    data['_filename'] = filename
                    results[scenario].append(data)
                    break
                    
        except Exception as e:
            print(f"Warning: Failed to load {file_path}: {e}")
    
    return results


def extract_metrics(data: Dict) -> Dict[str, float]:
    """Extract relevant metrics from k6 result data."""
    metrics = {}
    
    if 'metrics' not in data:
        return metrics
    
    k6_metrics = data['metrics']
    
    # HTTP request duration
    if 'http_req_duration' in k6_metrics:
        dur = k6_metrics['http_req_duration'].get('values', {})
        metrics['latency_avg'] = dur.get('avg')
        metrics['latency_min'] = dur.get('min')
        metrics['latency_max'] = dur.get('max')
        metrics['latency_p50'] = dur.get('p(50)')
        metrics['latency_p90'] = dur.get('p(90)')
        metrics['latency_p95'] = dur.get('p(95)')
        metrics['latency_p99'] = dur.get('p(99)')
    
    # Throughput
    if 'http_reqs' in k6_metrics:
        reqs = k6_metrics['http_reqs'].get('values', {})
        metrics['total_requests'] = reqs.get('count')
        metrics['throughput_rps'] = reqs.get('rate')
    
    # Error rate
    if 'http_req_failed' in k6_metrics:
        failed = k6_metrics['http_req_failed'].get('values', {})
        metrics['error_rate'] = failed.get('rate', 0) * 100  # Convert to percentage
    
    # Custom metrics
    if 'processing_time_ms' in k6_metrics:
        proc = k6_metrics['processing_time_ms'].get('values', {})
        metrics['processing_time_avg'] = proc.get('avg')
        metrics['processing_time_p95'] = proc.get('p(95)')
    
    if 'cold_start_latency' in k6_metrics:
        cold = k6_metrics['cold_start_latency'].get('values', {})
        metrics['cold_start_avg'] = cold.get('avg')
        metrics['cold_start_p95'] = cold.get('p(95)')
    
    return metrics


def create_comparison_table(results: Dict[str, List[Dict]], scenario: str) -> pd.DataFrame:
    """Create comparison table for a specific scenario."""
    rows = []
    
    for data in results.get(scenario, []):
        platform = data.get('_platform', 'unknown')
        metrics = extract_metrics(data)
        
        row = {'Platform': platform}
        row.update(metrics)
        rows.append(row)
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    
    # Aggregate by platform if multiple runs
    if len(df) > 0:
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df_grouped = df.groupby('Platform')[numeric_cols].agg(['mean', 'std']).reset_index()
        return df_grouped
    
    return df


def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate statistical measures for a list of values."""
    if not values or all(v is None for v in values):
        return {}
    
    clean_values = [v for v in values if v is not None]
    
    if len(clean_values) < 2:
        return {
            'mean': clean_values[0] if clean_values else None,
            'std': 0,
            'ci_lower': clean_values[0] if clean_values else None,
            'ci_upper': clean_values[0] if clean_values else None
        }
    
    arr = np.array(clean_values)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    
    # 95% confidence interval
    ci = stats.t.interval(0.95, len(arr)-1, loc=mean, scale=stats.sem(arr))
    
    return {
        'mean': mean,
        'std': std,
        'ci_lower': ci[0],
        'ci_upper': ci[1]
    }


def generate_latex_table(df: pd.DataFrame, caption: str, label: str) -> str:
    """Generate LaTeX table code for paper inclusion."""
    if df.empty:
        return f"% No data available for {label}"
    
    latex = df.to_latex(index=False, float_format="%.2f", escape=False)
    
    # Add caption and label
    latex = latex.replace('\\begin{tabular}', 
                          f'\\begin{{table}}[htbp]\n\\centering\n\\caption{{{caption}}}\n\\label{{{label}}}\n\\begin{{tabular}}')
    latex = latex.replace('\\end{tabular}', '\\end{tabular}\n\\end{table}')
    
    return latex


def analyze_performance_difference(results: Dict[str, List[Dict]], scenario: str) -> Dict[str, Any]:
    """Analyze performance difference between platforms."""
    cloudflare_metrics = []
    lambda_metrics = []
    
    for data in results.get(scenario, []):
        metrics = extract_metrics(data)
        platform = data.get('_platform')
        
        if platform == 'cloudflare':
            cloudflare_metrics.append(metrics)
        elif platform == 'lambda':
            lambda_metrics.append(metrics)
    
    analysis = {}
    
    if cloudflare_metrics and lambda_metrics:
        # Compare latency
        cf_latency = [m.get('latency_p95') for m in cloudflare_metrics if m.get('latency_p95')]
        lambda_latency = [m.get('latency_p95') for m in lambda_metrics if m.get('latency_p95')]
        
        if cf_latency and lambda_latency:
            cf_mean = np.mean(cf_latency)
            lambda_mean = np.mean(lambda_latency)
            
            analysis['latency_improvement_pct'] = ((lambda_mean - cf_mean) / lambda_mean) * 100
            analysis['cloudflare_p95_mean'] = cf_mean
            analysis['lambda_p95_mean'] = lambda_mean
            
            # Statistical significance test
            if len(cf_latency) >= 2 and len(lambda_latency) >= 2:
                t_stat, p_value = stats.ttest_ind(cf_latency, lambda_latency)
                analysis['t_statistic'] = t_stat
                analysis['p_value'] = p_value
                analysis['significant'] = p_value < 0.05
    
    return analysis


def generate_summary_report(results: Dict[str, List[Dict]], output_dir: str):
    """Generate comprehensive summary report."""
    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("CRYPTO EDGE BENCHMARK - ANALYSIS REPORT")
    report_lines.append(f"Generated: {datetime.now().isoformat()}")
    report_lines.append("=" * 70)
    report_lines.append("")
    
    for scenario in ['cold-start', 'warm-performance', 'load-test', 'burst-test']:
        report_lines.append(f"\n{'='*50}")
        report_lines.append(f"SCENARIO: {scenario.upper()}")
        report_lines.append(f"{'='*50}")
        
        df = create_comparison_table(results, scenario)
        if not df.empty:
            report_lines.append(tabulate(df, headers='keys', tablefmt='grid', floatfmt='.2f'))
            
            analysis = analyze_performance_difference(results, scenario)
            if analysis:
                report_lines.append(f"\nPerformance Analysis:")
                if 'latency_improvement_pct' in analysis:
                    report_lines.append(f"  Cloudflare P95: {analysis['cloudflare_p95_mean']:.2f} ms")
                    report_lines.append(f"  Lambda P95: {analysis['lambda_p95_mean']:.2f} ms")
                    report_lines.append(f"  Improvement: {analysis['latency_improvement_pct']:.1f}%")
                if 'significant' in analysis:
                    sig_str = "Yes" if analysis['significant'] else "No"
                    report_lines.append(f"  Statistically Significant (p<0.05): {sig_str}")
                    report_lines.append(f"  p-value: {analysis['p_value']:.4f}")
        else:
            report_lines.append("  No data available for this scenario")
    
    report_lines.append("\n" + "=" * 70)
    report_lines.append("END OF REPORT")
    report_lines.append("=" * 70)
    
    report_text = "\n".join(report_lines)
    
    # Save report
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, 'analysis_report.txt')
    with open(report_path, 'w') as f:
        f.write(report_text)
    
    print(report_text)
    print(f"\nReport saved to: {report_path}")
    
    return report_text


def export_for_paper(results: Dict[str, List[Dict]], output_dir: str):
    """Export data in formats suitable for paper inclusion."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Export CSV for each scenario
    for scenario in ['cold-start', 'warm-performance', 'load-test', 'burst-test']:
        df = create_comparison_table(results, scenario)
        if not df.empty:
            csv_path = os.path.join(output_dir, f'{scenario}_comparison.csv')
            df.to_csv(csv_path, index=False)
            print(f"Saved: {csv_path}")
            
            # Generate LaTeX table
            latex = generate_latex_table(
                df, 
                f"Performance comparison for {scenario} scenario",
                f"tab:{scenario.replace('-', '_')}"
            )
            latex_path = os.path.join(output_dir, f'{scenario}_table.tex')
            with open(latex_path, 'w') as f:
                f.write(latex)
            print(f"Saved: {latex_path}")


def main():
    parser = argparse.ArgumentParser(description='Analyze benchmark results')
    parser.add_argument('--input-dir', default='benchmark/results', 
                        help='Directory containing benchmark JSON files')
    parser.add_argument('--output-dir', default='benchmark/analysis/output',
                        help='Directory for output files')
    
    args = parser.parse_args()
    
    print(f"Loading results from: {args.input_dir}")
    results = load_benchmark_results(args.input_dir)
    
    total_files = sum(len(v) for v in results.values())
    print(f"Loaded {total_files} result files")
    
    if total_files == 0:
        print("No benchmark results found. Run benchmarks first.")
        return
    
    generate_summary_report(results, args.output_dir)
    export_for_paper(results, args.output_dir)


if __name__ == '__main__':
    main()
