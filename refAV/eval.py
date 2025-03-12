from av2.evaluation.scenario_mining.eval import evaluate
from av2.datasets.sensor.splits import TEST, TRAIN, VAL
from av2.datasets.sensor.constants import AnnotationCategories
from paths import AV2_DATA_DIR, SM_PRED_DIR, LLM_DEF_DIR, SM_DATA_DIR

from utils import *
from scenario_prediction import predict_scenario_from_description
import pickle
import random
import json
from tqdm import tqdm
import time
import copy
import argparse
import glob
import re
import logging
import faulthandler


def evaluate_baseline(description,
                      log_id,
                      baseline_pred_dir:Path,
                      gt_pkl_dir, scenario_pred_dir):
    
    gt_pkl = gt_pkl_dir / log_id / f'{description}_{log_id[:8]}_ref_gt.pkl'
    pred_pkl = baseline_pred_dir / log_id / f'{description}_{log_id[:8]}_ref_predictions.pkl'

    if not pred_pkl.exists():
        pred_pkl = create_baseline_prediction(description, log_id, baseline_pred_dir, scenario_pred_dir)

    evaluate(pred_pkl, gt_pkl, objective_metric='HOTA', max_range_m=100, dataset_dir=AV2_DATA_DIR, out=str('eval'))


def create_baseline_prediction(description, log_id, baseline_pred_dir, scenario_pred_dir):

    pred_path = baseline_pred_dir / log_id / f'{description}_{log_id[:8]}_ref_predictions.pkl'
    if pred_path.exists():
        return pred_path

    #Used in exec(scenario) code
    is_gt = False
    output_dir = baseline_pred_dir 
    log_dir:Path = baseline_pred_dir / log_id
    
    try:
        scenario_filename = scenario_pred_dir / f'{description}.txt'
        print(scenario_filename)
        if scenario_filename.exists():
            print('Cached scenario prediction found')
        else:
            scenario_filename = predict_scenario_from_description(description, output_dir=scenario_pred_dir)
        
        with open(scenario_filename, 'r') as f:
            scenario = f.read()
            exec(scenario)

    except:
        # Sometimes Claude will generate scenario definitions with bugs
        # In this case, output the default prediction of no referred tracks
        pred_path = create_default_prediction(description, log_id, baseline_pred_dir)

    return pred_path

def create_default_prediction(description, log_id, baseline_pred_dir):
    
    #Used in exec(scenario) code
    log_dir:Path = baseline_pred_dir / log_id
    
    empty_set = {}
    output_scenario(empty_set, description, log_dir, baseline_pred_dir, is_gt=False)

    pred_path = baseline_pred_dir / log_id / f'{description}_{log_id[:8]}_ref_predictions.pkl'
    if pred_path.exists():
        print('Default scenario prediction correctly generated.')
    else:
        print('Default scenario prediction failed.')

    return pred_path


def evaluate_pkls(pred_pkl, gt_pkl):
    with open(pred_pkl, 'rb') as f:
        predictions = pickle.load(f)

    with open(gt_pkl, 'rb') as f:
        labels = pickle.load(f)

    evaluate(predictions, labels, objective_metric='HOTA', max_range_m=100, dataset_dir=AV2_DATA_DIR, out='output/evaluation')


def clear_pkl_files(dir:Path):
    for file in dir.iterdir():
        if file.is_file() and file.suffix == '.pkl':
            file.unlink()
            print(f'{file.name} deleted')


def combine_matching_pkls(gt_base_dir, pred_base_dir, output_dir):
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Get all log_ids from both directories
    gt_log_ids = {d.name: d for d in Path(gt_base_dir).iterdir() if d.is_dir()}
    pred_log_ids = {d.name: d for d in Path(pred_base_dir).iterdir() if d.is_dir()}
    
    # Find matching log_ids
    matching_log_ids = set(gt_log_ids.keys()) & set(pred_log_ids.keys())
    
    # Initialize combined dictionaries
    combined_gt = {}
    combined_pred = {}
    
    # For each matching log_id
    for log_id in matching_log_ids:

        gt_log_dir = gt_log_ids[log_id]
        pred_log_dir = pred_log_ids[log_id]
        
        # Get all PKL files in these directories
        gt_files = {f.stem.replace('_ref_gt', ''): f 
                   for f in gt_log_dir.glob('*_ref_gt.pkl')}
        pred_files = {f.stem.replace('_ref_predictions', ''): f 
                     for f in pred_log_dir.glob('*_ref_predictions.pkl')}
        
        # Find matching files within this log_id
        matching_keys = set(gt_files.keys()) & set(pred_files.keys())
        # Combine matching files
        for key in matching_keys:

            # Load GT file
            with open(gt_files[key], 'rb') as f:
                gt_data = pickle.load(f)
                combined_gt.update(copy.deepcopy(gt_data))
                
            # Load prediction file
            with open(pred_files[key], 'rb') as f:
                pred_data = pickle.load(f)
                combined_pred.update(copy.deepcopy(pred_data))

        # Report unmatched files for this log_id
        unmatched_gt = set(gt_files.keys()) - matching_keys
        unmatched_pred = set(pred_files.keys()) - matching_keys
        
        if unmatched_gt:
            print(f"\nUnmatched GT files in log_id {log_id}:")
            for name in unmatched_gt:
                print(f"- {name}")
        
        if unmatched_pred:
            print(f"\nUnmatched prediction files in log_id {log_id}:")
            for name in unmatched_pred:
                print(f"- {name}")
    
    # Save combined files
    if combined_gt:
        with open(os.path.join(output_dir, 'combined_gt.pkl'), 'wb') as f:
            pickle.dump(combined_gt, f)
    
    if combined_pred:
        with open(os.path.join(output_dir, 'combined_predictions.pkl'), 'wb') as f:
            pickle.dump(combined_pred, f)
    
    # Print statistics
    print(f"\nFound {len(matching_log_ids)} matching log_ids")
    print(f"Combined GT file contains {len(combined_gt)} entries")
    print(f"Combined predictions file contains {len(combined_pred)} entries")
    
    # Report unmatched log_ids
    unmatched_gt_logs = set(gt_log_ids.keys()) - matching_log_ids
    unmatched_pred_logs = set(pred_log_ids.keys()) - matching_log_ids
    
    if unmatched_gt_logs:
        print("\nLog IDs in GT without matching predictions directory:")
        for log_id in unmatched_gt_logs:
            print(f"- {log_id}")
    
    if unmatched_pred_logs:
        print("\nLog IDs in predictions without matching GT directory:")
        for log_id in unmatched_pred_logs:
            print(f"- {log_id}")
    
def file_contains_string(directory, search_string):
    return any(search_string in file.name for file in Path(directory).iterdir() if file.is_file())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Example script with arguments")
    parser.add_argument("--split", type=str, help="An optional argument", default='val')
    parser.add_argument("--start_log_index", type=int, help="An optional argument", default=0)
    parser.add_argument("--end_log_index", type=int, help="An optional argument", default=700)
    args = parser.parse_args()
    split = args.split

    faulthandler.enable()
    logging.basicConfig(
    filename='output/evaluation_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if split == 'test':
        logs_to_analyze = list(TEST)[args.start_log_index:min(args.end_log_index, len(TEST))]
    elif split == 'train':
        logs_to_analyze = list(TRAIN)[args.start_log_index:min(args.end_log_index, len(TRAIN))]
    elif split == 'val':
        logs_to_analyze = list(VAL)[args.start_log_index:min(args.end_log_index, len(VAL))]
    else:
        print('--split must be one of train, test, or val.')

    log_prompt_input_path = Path('av2_sm_downloads/log_prompt_pairs_val.json')
    eval_output_dir = Path(f'output/evaluation/{split}')

    with open(log_prompt_input_path, 'rb') as f:
        log_prompts = json.load(f)

    
    for log_id, prompts in log_prompts.items():
        for prompt in prompts:
            create_baseline_prediction(prompt, log_id, SM_PRED_DIR, LLM_DEF_DIR)
    
    combine_matching_pkls(SM_DATA_DIR, SM_PRED_DIR, eval_output_dir)
    evaluate_pkls(eval_output_dir / 'combined_predictions.pkl', eval_output_dir / 'combined_gt.pkl')

#Do not use Trinity-1-4 or Trinity-1-34 to generate scenario visualizations. Nvidia drivers incompatible with Pyvista

    
