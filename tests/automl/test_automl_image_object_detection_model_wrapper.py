# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

"""Tests for wrap_model function on AutoML Object Detection models"""

import base64
import copy
import io
import json
import os
import sys
import tempfile

import azureml.automl.core.shared.constants as shared_constants
import mlflow
import pytest
from azureml.automl.dnn.vision.common.mlflow.mlflow_model_wrapper import \
    MLFlowImagesModelWrapper
from azureml.automl.dnn.vision.common.model_export_utils import (
    _get_mlflow_signature, _get_scoring_method)
from azureml.automl.dnn.vision.object_detection.common.constants import \
    ModelNames
from azureml.automl.dnn.vision.object_detection.models import \
    object_detection_model_wrappers
from common_vision_utils import (IMAGE, IMAGE_SIZE, load_base64_images,
                                 load_object_fridge_dataset)
from constants import UTF8
from ml_wrappers import wrap_model
from ml_wrappers.common.constants import ModelTask
from ml_wrappers.model.image_model_wrapper import (MLflowDRiseWrapper,
                                                   PytorchDRiseWrapper)
from PIL import Image
from wrapper_validator import (
    validate_wrapped_object_detection_custom_model,
    validate_wrapped_object_detection_mlflow_drise_model,
    validate_wrapped_object_detection_model)

try:
    import torch
    from torchvision import transforms as T
except ImportError:
    print('Could not import torch, required if using a PyTorch model')


RGB = 'RGB'
BLACK = 'black'
PNG = 'PNG'


def create_black_image(width, height):
    return Image.new(RGB, (width, height), BLACK)


def image_to_base64(image, image_type=PNG):
    buffer = io.BytesIO()
    image.save(buffer, format=image_type)
    img_data = buffer.getvalue()
    return base64.b64encode(img_data).decode(UTF8)


def load_mlflow_model(class_names, model_settings=None):
    model_name = ModelNames.FASTER_RCNN_RESNET50_FPN

    with tempfile.TemporaryDirectory() as tmp_output_dir:
        task_type = shared_constants.Tasks.IMAGE_OBJECT_DETECTION
        number_of_classes = len(class_names)
        model_wrapper = object_detection_model_wrappers \
            .ObjectDetectionModelFactory() \
            .get_model_wrapper(number_of_classes, model_name)

        # mock for Mlflow model generation
        model_file = os.path.join(tmp_output_dir, "model.pt")
        if model_settings is None:
            model_settings = model_wrapper.model_settings.get_settings_dict()
        torch.save(
            {
                'model_name': model_name,
                'number_of_classes': number_of_classes,
                'model_state': copy.deepcopy(model_wrapper.state_dict()),
                'specs': {
                    'model_settings':
                    model_settings,
                    'inference_settings': model_wrapper.inference_settings,
                    'classes': model_wrapper.classes,
                    'model_specs': {
                        'model_settings':
                        model_settings,
                        'inference_settings':
                        model_wrapper.inference_settings,
                    },
                },
            },
            model_file
        )
        settings_file = os.path.join(
            tmp_output_dir,
            shared_constants.MLFlowLiterals.MODEL_SETTINGS_FILENAME
        )
        remote_path = os.path.join(tmp_output_dir, "outputs")

        with open(settings_file, 'w') as f:
            json.dump({}, f)

        conda_env = {
            'channels': ['conda-forge', 'pytorch'],
            'dependencies': [
                'python=3.9',
                'numpy==1.26.4',
                'pytorch==2.2.0',
                'torchvision==0.17.2',
                {'pip': ['azureml-automl-dnn-vision']}
            ],
            'name': 'azureml-automl-dnn-vision-env'
        }

        mlflow_model_wrapper = MLFlowImagesModelWrapper(
            model_settings=model_settings,
            task_type=task_type,
            scoring_method=_get_scoring_method(task_type)
        )
        print("Saving mlflow model at {}".format(remote_path))
        mlflow.pyfunc.save_model(
            path=remote_path,
            python_model=mlflow_model_wrapper,
            artifacts={
                "model": model_file,
                "settings": settings_file
            },
            conda_env=conda_env,
            signature=_get_mlflow_signature(task_type)
        )
        return mlflow.pyfunc.load_model(remote_path)


@pytest.mark.usefixtures('_clean_dir')
class TestImageModelWrapper(object):
    # Skip for older versions of python as azureml-automl-dnn-vision
    # works with 3.9 only
    @pytest.mark.skipif(
        sys.version_info < (3, 9),
        reason=('azureml-automl-dnn-vision not supported '
                'for older versions of python'))
    @pytest.mark.skipif(
        sys.version_info >= (3, 10),
        reason=('azureml-automl-dnn-vision not supported '
                'for newer versions of python'))
    def test_wrap_automl_object_detection_model(self):
        data = load_object_fridge_dataset()[1:4]
        class_names = ['can', 'carton', 'milk_bottle', 'water_bottle']
        mlflow_model = load_mlflow_model(class_names)
        # load the paths as base64 images
        data = load_base64_images(data, return_image_size=True)

        wrapped_model = wrap_model(
            mlflow_model, data, ModelTask.OBJECT_DETECTION,
            classes=class_names)
        validate_wrapped_object_detection_model(wrapped_model, data)

        # Now test what happens when an invalid classes input is given
        label_dict = {'can': 1, 'carton': 2,
                      'milk_bottle': 3, 'water_bottle': 4}
        exp_err = "classes parameter not a list of class labels"
        with pytest.raises(KeyError, match=exp_err):
            wrap_model(mlflow_model,
                       data,
                       ModelTask.OBJECT_DETECTION,
                       classes=label_dict)

    # Skip for older versions of python as azureml-automl-dnn-vision
    # works with 3.9 only
    @pytest.mark.skipif(
        sys.version_info < (3, 9),
        reason=('azureml-automl-dnn-vision not supported '
                'for older versions of python'))
    @pytest.mark.skipif(
        sys.version_info >= (3, 10),
        reason=('azureml-automl-dnn-vision not supported '
                'for newer versions of python'))
    def test_automl_object_detection_empty_predictions(self):
        data = load_object_fridge_dataset()[1:2]
        class_names = ['can', 'carton', 'milk_bottle', 'water_bottle']

        model_settings = {
            'min_size': 10,
            'box_score_thresh': 0.9,
            'nms_iou_thresh': 0.9
        }
        mlflow_model = load_mlflow_model(class_names, model_settings)

        # load the paths as base64 images
        data = load_base64_images(data, return_image_size=True)

        # Now test an empty black image as input
        data = data[0:1]
        # Create a black image with the specified dimensions
        shape = data[IMAGE_SIZE][0]
        width = shape[0]
        height = shape[1]
        black_image = create_black_image(width, height)
        # Convert the black image to a base64 encoded string
        base64_string = image_to_base64(black_image)
        data[IMAGE][0] = base64_string
        data[IMAGE_SIZE][0] = (width, height)
        wrapped_model = wrap_model(
            mlflow_model, data, ModelTask.OBJECT_DETECTION,
            classes=class_names)
        validate_wrapped_object_detection_model(wrapped_model, data, 1)

    @pytest.mark.skipif(
        sys.version_info < (3, 9),
        reason=('azureml-automl-dnn-vision not supported '
                'for older versions of python'))
    @pytest.mark.skipif(
        sys.version_info >= (3, 10),
        reason=('azureml-automl-dnn-vision not supported '
                'for newer versions of python'))
    @pytest.mark.parametrize('extract_raw_model',
                             [True, False])
    def test_drise_wrap_automl_object_detection_model(self, extract_raw_model):
        data = load_object_fridge_dataset()[3:4]
        class_names = ['can', 'carton', 'milk_bottle', 'water_bottle']
        mlflow_model = load_mlflow_model(class_names)

        # load the paths as base64 images
        data = load_base64_images(data, return_image_size=True)

        if extract_raw_model:
            python_model = mlflow_model._model_impl.python_model
            automl_wrapper = python_model._model
            inner_model = automl_wrapper._model
            number_of_classes = automl_wrapper._number_of_classes
            transforms = automl_wrapper.get_inference_transform()
            wrapped_model = PytorchDRiseWrapper(
                inner_model, number_of_classes,
                transforms=transforms,
                iou_threshold=0.25,
                score_threshold=0.5)
            base64str = data.iloc[0, 0]
            base64bytes = base64.b64decode(base64str)
            image = Image.open(io.BytesIO(base64bytes)).convert(RGB)
            validate_wrapped_object_detection_custom_model(
                wrapped_model,
                T.ToTensor()(image).repeat(2, 1, 1, 1),
                has_predict_proba=False)
        else:
            wrapped_model = MLflowDRiseWrapper(mlflow_model,
                                               classes=class_names)
            validate_wrapped_object_detection_mlflow_drise_model(
                wrapped_model, data)
