"""
Benchmark Visualization Script

Creates publication-quality charts for the research paper.

Usage:
    python visualize.py [--input-dir benchmark/results] [--output-dir benchmark/analysis/output/figures]
"""

import json
import os
import glob
import argparse
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import FuncFormatter

# Set publication-quality defaults
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams.update({
    'font.size': 12,
    'font.family': 'serif',
    'axes.labelsize': 14,
    'axes.titlesize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'figure.figsize': (8, 6),
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.1
})

# Color palette for platforms
PLATFORM_COLORS = {
    'cloudflare': '#F38020',  # Cloudflare orange
    'vercel': '#000000',      # Vercel black
    'lambda': '#FF9900',      # AWS orange
    'Cloudflare Workers': '#F38020',
    'Vercel Edge': '#000000',
    'AWS Lambda@Edge': '#FF9900'
}


def load_benchmark_results(input_dir: str) -> Dict[str, List[Dict]]:
    """Load all benchmark result JSON files."""
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
            
            for scenario in results.keys():
                if scenario in filename:
                    platform = 'Cloudflare Workers' if 'cloudflare' in filename else 'Vercel Edge' if 'vercel' in filename else 'AWS Lambda@Edge' if 'lambda' in filename else 'Unknown'
                    data['_platform'] = platform
                    data['_filename'] = filename
                    results[scenario].append(data)
                    break
                    
        except Exception as e:
            print(f"Warning: Failed to load {file_path}: {e}")
    
    return results


def extract_latency_data(results: Dict[str, List[Dict]], scenario: str) -> pd.DataFrame:
    """Extract latency data for visualization."""
    rows = []
    
    for data in results.get(scenario, []):
        platform = data.get('_platform', 'Unknown')
        
        if 'metrics' not in data:
            continue
            
        metrics = data['metrics']
        
        if 'http_req_duration' in metrics:
            dur = metrics['http_req_duration'].get('values', {})
            rows.append({
                'Platform': platform,
                'P50': dur.get('p(50)'),
                'P90': dur.get('p(90)'),
                'P95': dur.get('p(95)'),
                'P99': dur.get('p(99)'),
                'Avg': dur.get('avg'),
                'Min': dur.get('min'),
                'Max': dur.get('max')
            })
    
    return pd.DataFrame(rows)


def plot_latency_comparison(results: Dict[str, List[Dict]], output_dir: str):
    """Create latency comparison bar chart."""
    df = extract_latency_data(results, 'warm-performance')
    
    if df.empty:
        print("No warm-performance data available for latency comparison")
        return
    
    # Aggregate by platform
    df_agg = df.groupby('Platform').agg({
        'P50': 'mean',
        'P95': 'mean',
        'P99': 'mean'
    }).reset_index()
    
    # Create grouped bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    
    x = np.arange(len(df_agg))
    width = 0.25
    
    bars1 = ax.bar(x - width, df_agg['P50'], width, label='P50', color='#2ecc71')
    bars2 = ax.bar(x, df_agg['P95'], width, label='P95', color='#3498db')
    bars3 = ax.bar(x + width, df_agg['P99'], width, label='P99', color='#e74c3c')
    
    ax.set_xlabel('Platform')
    ax.set_ylabel('Latency (ms)')
    ax.set_title('Latency Percentiles Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(df_agg['Platform'])
    ax.legend()
    
    # Add value labels on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.1f}',
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'latency_comparison.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))  # Also save as PDF for paper
    print(f"Saved: {output_path}")
    plt.close()


def plot_latency_distribution(results: Dict[str, List[Dict]], output_dir: str):
    """Create latency distribution box plot."""
    # This would require raw latency data, which k6 can export with --out json
    # For now, we'll create a synthetic visualization based on percentiles
    
    df = extract_latency_data(results, 'warm-performance')
    
    if df.empty:
        print("No data available for latency distribution")
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    platforms = df['Platform'].unique()
    colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in platforms]
    
    # Create box-like visualization from percentiles
    for i, platform in enumerate(platforms):
        platform_data = df[df['Platform'] == platform].iloc[0]
        
        # Create box plot manually
        box_data = {
            'min': platform_data['Min'],
            'q1': platform_data['P50'] * 0.8,  # Approximate Q1
            'median': platform_data['P50'],
            'q3': platform_data['P95'],
            'max': platform_data['P99']
        }
        
        color = colors[i]
        
        # Draw box
        ax.bar(i, box_data['q3'] - box_data['q1'], bottom=box_data['q1'], 
               width=0.4, color=color, alpha=0.7, edgecolor='black')
        
        # Draw median line
        ax.hlines(box_data['median'], i - 0.2, i + 0.2, color='black', linewidth=2)
        
        # Draw whiskers
        ax.vlines(i, box_data['min'], box_data['q1'], color='black', linewidth=1)
        ax.vlines(i, box_data['q3'], box_data['max'], color='black', linewidth=1)
        ax.hlines(box_data['min'], i - 0.1, i + 0.1, color='black', linewidth=1)
        ax.hlines(box_data['max'], i - 0.1, i + 0.1, color='black', linewidth=1)
    
    ax.set_xlabel('Platform')
    ax.set_ylabel('Latency (ms)')
    ax.set_title('Latency Distribution by Platform')
    ax.set_xticks(range(len(platforms)))
    ax.set_xticklabels(platforms)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'latency_distribution.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))
    print(f"Saved: {output_path}")
    plt.close()


def plot_throughput_comparison(results: Dict[str, List[Dict]], output_dir: str):
    """Create throughput comparison chart."""
    rows = []
    
    for data in results.get('load-test', []):
        platform = data.get('_platform', 'Unknown')
        
        if 'metrics' not in data:
            continue
            
        metrics = data['metrics']
        
        if 'http_reqs' in metrics:
            reqs = metrics['http_reqs'].get('values', {})
            rows.append({
                'Platform': platform,
                'Throughput (req/s)': reqs.get('rate', 0),
                'Total Requests': reqs.get('count', 0)
            })
    
    df = pd.DataFrame(rows)
    
    if df.empty:
        print("No load-test data available for throughput comparison")
        return
    
    # Aggregate by platform
    df_agg = df.groupby('Platform')['Throughput (req/s)'].mean().reset_index()
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in df_agg['Platform']]
    bars = ax.bar(df_agg['Platform'], df_agg['Throughput (req/s)'], color=colors, edgecolor='black')
    
    ax.set_xlabel('Platform')
    ax.set_ylabel('Throughput (requests/second)')
    ax.set_title('Throughput Comparison Under Load')
    
    # Add value labels
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.1f}',
                   xy=(bar.get_x() + bar.get_width() / 2, height),
                   xytext=(0, 3),
                   textcoords="offset points",
                   ha='center', va='bottom', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'throughput_comparison.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))
    print(f"Saved: {output_path}")
    plt.close()


def plot_cold_start_comparison(results: Dict[str, List[Dict]], output_dir: str):
    """Create cold start latency comparison."""
    df = extract_latency_data(results, 'cold-start')
    
    if df.empty:
        print("No cold-start data available")
        return
    
    df_agg = df.groupby('Platform').agg({
        'P50': 'mean',
        'P95': 'mean',
        'Max': 'mean'
    }).reset_index()
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    x = np.arange(len(df_agg))
    width = 0.35
    
    colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in df_agg['Platform']]
    
    bars1 = ax.bar(x - width/2, df_agg['P95'], width, label='P95 Cold Start', 
                   color=colors, alpha=0.8, edgecolor='black')
    bars2 = ax.bar(x + width/2, df_agg['Max'], width, label='Max Cold Start',
                   color=colors, alpha=0.5, edgecolor='black', hatch='//')
    
    ax.set_xlabel('Platform')
    ax.set_ylabel('Cold Start Latency (ms)')
    ax.set_title('Cold Start Performance Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(df_agg['Platform'])
    ax.legend()
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'cold_start_comparison.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))
    print(f"Saved: {output_path}")
    plt.close()


def plot_error_rate_comparison(results: Dict[str, List[Dict]], output_dir: str):
    """Create error rate comparison."""
    rows = []
    
    for scenario in ['warm-performance', 'load-test', 'burst-test']:
        for data in results.get(scenario, []):
            platform = data.get('_platform', 'Unknown')
            
            if 'metrics' not in data:
                continue
            
            metrics = data['metrics']
            
            error_rate = 0
            if 'http_req_failed' in metrics:
                error_rate = metrics['http_req_failed'].get('values', {}).get('rate', 0) * 100
            
            rows.append({
                'Platform': platform,
                'Scenario': scenario,
                'Error Rate (%)': error_rate
            })
    
    df = pd.DataFrame(rows)
    
    if df.empty:
        print("No data available for error rate comparison")
        return
    
    # Pivot for grouped bar chart
    df_pivot = df.pivot_table(values='Error Rate (%)', 
                               index='Scenario', 
                               columns='Platform', 
                               aggfunc='mean').fillna(0)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    df_pivot.plot(kind='bar', ax=ax, color=[PLATFORM_COLORS.get(c, '#95a5a6') for c in df_pivot.columns],
                  edgecolor='black')
    
    ax.set_xlabel('Scenario')
    ax.set_ylabel('Error Rate (%)')
    ax.set_title('Error Rate Comparison Across Scenarios')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right')
    ax.legend(title='Platform')
    
    # Format y-axis as percentage
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f'{y:.2f}%'))
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'error_rate_comparison.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))
    print(f"Saved: {output_path}")
    plt.close()


def create_summary_dashboard(results: Dict[str, List[Dict]], output_dir: str):
    """Create a multi-panel summary dashboard."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    
    fig.suptitle('Edge Deployment Benchmark Summary', fontsize=16, fontweight='bold')
    
    # Panel 1: Latency comparison
    ax1 = axes[0, 0]
    df_latency = extract_latency_data(results, 'warm-performance')
    if not df_latency.empty:
        df_agg = df_latency.groupby('Platform')[['P50', 'P95', 'P99']].mean().reset_index()
        x = np.arange(len(df_agg))
        width = 0.25
        ax1.bar(x - width, df_agg['P50'], width, label='P50', color='#2ecc71')
        ax1.bar(x, df_agg['P95'], width, label='P95', color='#3498db')
        ax1.bar(x + width, df_agg['P99'], width, label='P99', color='#e74c3c')
        ax1.set_xticks(x)
        ax1.set_xticklabels(df_agg['Platform'], fontsize=10)
        ax1.legend(fontsize=9)
    ax1.set_title('Latency Percentiles (ms)')
    ax1.set_ylabel('Latency (ms)')
    
    # Panel 2: Cold start
    ax2 = axes[0, 1]
    df_cold = extract_latency_data(results, 'cold-start')
    if not df_cold.empty:
        df_agg = df_cold.groupby('Platform')['P95'].mean().reset_index()
        colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in df_agg['Platform']]
        ax2.bar(df_agg['Platform'], df_agg['P95'], color=colors, edgecolor='black')
    ax2.set_title('Cold Start P95 Latency (ms)')
    ax2.set_ylabel('Latency (ms)')
    
    # Panel 3: Throughput
    ax3 = axes[1, 0]
    throughput_data = []
    for data in results.get('load-test', []):
        platform = data.get('_platform', 'Unknown')
        if 'metrics' in data and 'http_reqs' in data['metrics']:
            rate = data['metrics']['http_reqs'].get('values', {}).get('rate', 0)
            throughput_data.append({'Platform': platform, 'Throughput': rate})
    if throughput_data:
        df_tp = pd.DataFrame(throughput_data).groupby('Platform')['Throughput'].mean().reset_index()
        colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in df_tp['Platform']]
        ax3.bar(df_tp['Platform'], df_tp['Throughput'], color=colors, edgecolor='black')
    ax3.set_title('Throughput (requests/second)')
    ax3.set_ylabel('req/s')
    
    # Panel 4: Error rates
    ax4 = axes[1, 1]
    error_data = []
    for scenario in ['load-test', 'burst-test']:
        for data in results.get(scenario, []):
            platform = data.get('_platform', 'Unknown')
            if 'metrics' in data and 'http_req_failed' in data['metrics']:
                error_rate = data['metrics']['http_req_failed'].get('values', {}).get('rate', 0) * 100
                error_data.append({'Platform': platform, 'Scenario': scenario, 'Error Rate': error_rate})
    if error_data:
        df_err = pd.DataFrame(error_data).groupby('Platform')['Error Rate'].mean().reset_index()
        colors = [PLATFORM_COLORS.get(p, '#95a5a6') for p in df_err['Platform']]
        ax4.bar(df_err['Platform'], df_err['Error Rate'], color=colors, edgecolor='black')
    ax4.set_title('Average Error Rate (%)')
    ax4.set_ylabel('Error Rate (%)')
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'benchmark_dashboard.png')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.png', '.pdf'))
    print(f"Saved: {output_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Visualize benchmark results')
    parser.add_argument('--input-dir', default='benchmark/results',
                        help='Directory containing benchmark JSON files')
    parser.add_argument('--output-dir', default='benchmark/analysis/output/figures',
                        help='Directory for output figures')
    
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    print(f"Loading results from: {args.input_dir}")
    results = load_benchmark_results(args.input_dir)
    
    total_files = sum(len(v) for v in results.values())
    print(f"Loaded {total_files} result files")
    
    if total_files == 0:
        print("No benchmark results found. Run benchmarks first.")
        print("Creating sample visualizations with placeholder data...")
        # Could create sample charts here for testing
        return
    
    print("\nGenerating visualizations...")
    plot_latency_comparison(results, args.output_dir)
    plot_latency_distribution(results, args.output_dir)
    plot_throughput_comparison(results, args.output_dir)
    plot_cold_start_comparison(results, args.output_dir)
    plot_error_rate_comparison(results, args.output_dir)
    create_summary_dashboard(results, args.output_dir)
    
    print("\nVisualization complete!")


if __name__ == '__main__':
    main()
