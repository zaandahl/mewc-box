import os
import json
import visualization.visualization_utils as viz_utils
from tqdm import tqdm
from pathlib import Path
from lib_common import read_yaml
from lib_tools import process_detections

def draw_box(json_detection, img, lower_conf, valid):
    if(valid == True):
        viz_utils.render_detection_bounding_boxes(
            [json_detection], 
            img,
            confidence_threshold=float(lower_conf))
    return(img)

config = read_yaml('config.yaml')
for conf_key in config.keys():
    if conf_key in os.environ:
        config[conf_key] = os.environ[conf_key]

json_path = Path(config['INPUT_DIR'],config['MD_FILE'])

with open(json_path, "r") as read_json:
    json_data = json.load(read_json)

if config['SUBFOLDER'] == 'True':
    sort_text = ' and sorting into subfolders'
else:
    sort_text = ''
print("Drawing boxes on " + str(len(json_data['images'])) + " images from " + config['MD_FILE'] + sort_text)
for json_image in tqdm(json_data['images']):
    try:
        valid_image = process_detections(json_image,config['OVERLAP'],config['EDGE_DIST'],config['MIN_EDGES'],config['UPPER_CONF'],config['LOWER_CONF'])
        image_name = Path(json_image.get('file')).name
        image_stem = Path(json_image.get('file')).stem
        image_ext = Path(json_image.get('file')).suffix
        input_path = Path(config['INPUT_DIR'],image_name)
        detections = sum(valid_image)
        if config['SUBFOLDER'] == 'True':
            Path(config['INPUT_DIR'],config['BLANK_DIR']).mkdir(parents=True,exist_ok=True)
            for cat_name in json_data['detection_categories']:
                Path(config['INPUT_DIR'],json_data['detection_categories'][cat_name]).mkdir(parents=True,exist_ok=True)
        if detections == 0 and config['SUBFOLDER'] == 'True':
            output_path = Path(config['INPUT_DIR'],config['BLANK_DIR'],image_name)
            input_path.rename(output_path)
        else:
            img = viz_utils.load_image(input_path)
            exif = img.info['exif']
            for i in range(len(valid_image)):
                img = draw_box(json_image['detections'][i],img,config['LOWER_CONF'],valid_image[i])
            if config['SUBFOLDER'] == 'True':
                image_cat = json_image['detections'][len(json_image['detections'])-1]['category']
                output_path = Path(config['INPUT_DIR'],json_data['detection_categories'][image_cat],image_name)
                img.save(output_path, exif=exif)
                input_path.unlink(missing_ok=True)
            else:
                img.save(input_path, exif=exif)
    except: pass
