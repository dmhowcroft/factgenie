#!/usr/bin/env python3

import traceback
from openai import OpenAI
from textwrap import dedent
import argparse
import yaml
import json
import sys

from pathlib import Path
import os
import coloredlogs
import logging
import time
import requests
import copy

# logging.basicConfig(format="%(message)s", level=logging.INFO, datefmt="%H:%M:%S")
coloredlogs.install(level="INFO", fmt="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DIR_PATH = os.path.dirname(__file__)
LLM_ANNOTATION_DIR = os.path.join(DIR_PATH, "annotations")


class LLMMetricFactory:
    @staticmethod
    def get_metric(config):
        metric_type = config["type"]  # TODO (oplatek) rename to metric_type to be explicit in the config
        model = config["model"]

        # TODO (oplatek) change the string in metric_type to exactly match the metric names so the configs and code in this module is consistent;-) -> prefix them with llm- !
        if metric_type == "openai":
            return OpenAIMetric(config)
        elif metric_type == "ollama":
            # we implemented specific input postprocessing for Llama 3
            if model.startswith("llama3"):
                return Llama3Metric(config)
            else:
                return OllamaMetric(config)
        elif metric_type == "ollama-logicnlg":
            return LogicNLGMarkdownOllamaMetric(config)
        else:
            raise NotImplementedError(f"The metric type {metric_type} is not implemented. All yaml files in factgenie/llm-eval should use existing metrics!")


class LLMMetric:
    def __init__(self, config, metric_name):
        self.metric_name = metric_name
        self.annotation_key = config.get("annotation_key", "errors")

        self.system_msg = config.get("system_msg", None)
        if self.system_msg is None:
            logger.warning("System message (`system_msg`) field not set, using an empty string")
            self.system_msg = ""

        self.metric_prompt_template = config.get("prompt_template", None)

        if self.metric_prompt_template is None:
            raise ValueError("Prompt template (`prompt_template`) field is missing in the config")

    def postprocess_annotations(self, text, model_json):
        annotation_list = []
        current_pos = 0

        if self.annotation_key not in model_json:
            logger.error(f"Cannot find {self.annotation_key=} in {model_json=}")
            return []

        for annotation in model_json[self.annotation_key]:
            # find the `start` index of the error in the text
            start_pos = text.lower().find(annotation["text"].lower(), current_pos)

            if current_pos != 0 and start_pos == -1:
                # try from the beginning
                start_pos = text.find(annotation["text"])

            if start_pos == -1:
                logger.warning(f"Cannot find {annotation=} in text {text}, skipping")
                continue

            annotation["start"] = start_pos
            annotation_list.append(copy.deepcopy(annotation))

            current_pos = start_pos + len(annotation["text"])

        return annotation_list

    def preprocess_data_for_prompt(self, data):
        """Override this method to change the format how the data is presented in the prompt. See self.prompt() method for usage."""
        return data

    def prompt(self, data, text):
        data4prompt = self.preprocess_data_for_prompt(data)
        return self.metric_prompt_template.format(data=data4prompt, text=text)

    def annotate_example(self, data, text):
        raise NotImplementedError("Override this method in the subclass to call the LLM API")


class OpenAIMetric(LLMMetric):
    def __init__(self, config, name=None):
        name = "llm-openai-" + config["model"] if name is None else name
        super().__init__(config, name)
        self.client = OpenAI()
        self.model = config["model"]

    def annotate_example(self, data, text):
        try:
            prompt = self.prompt(data, text)

            logger.debug(f"Calling OpenAI API with prompt: {prompt}")
            response = self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self.system_msg},
                    {"role": "user", "content": prompt},
                ],
            )
            annotation_str = response.choices[0].message.content
            j = json.loads(annotation_str)
            logger.info(j)

            return self.postprocess_annotations(text=text, model_json=j)
        except Exception as e:
            logger.error(e)
            return {"error": str(e)}


class OllamaMetric(LLMMetric):
    def __init__(self, config, name=None):
        name = "llm-ollama-" + config["model"] if name is None else name
        super().__init__(config, name)
        self.API_URL = config.get("api_url", None)

        if self.API_URL is None:
            raise ValueError("API URL (`api_url`) field is missing in the config")

        self.model_args = config["model_args"]
        self.model = config["model"]
        self.seed = self.model_args.get("seed", None)

    def postprocess_output(self, output):
        output = output.strip()
        j = json.loads(output)
        return j

    def annotate_example(self, data, text):
        prompt = self.prompt(data=data, text=text)
        request_d = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"seed": self.seed, "temperature": 0},
        }
        msg = f"Ollama API {self.API_URL} with args:\n\t{request_d}"
        response, annotation_str, j = None, None, None 
        try:
            logger.debug(f"Calling {msg}")
            response = requests.post(self.API_URL, json=request_d)
            annotation_str = response.json()["response"]

            j = self.postprocess_output(annotation_str)
            logger.info(j)
            return self.postprocess_annotations(text=text, model_json=j)
        except Exception as e:
            logger.error(f"Called {msg}\n\n and received\n\t{response=}\n\t{annotation_str=}\n\t{j=}\nbefore the error:{e}")
            traceback.print_exc()
            return {"error": str(e)}


class LogicNLGMarkdownOllamaMetric(OllamaMetric):
    def __init__(self, config):
        name = "llm-ollama-logicnlg" + config["model"]
        self._table_str_f = config.get("table_str_f", "to_string")
        super().__init__(config, name)

    def preprocess_data_for_prompt(self, example):
        import pandas as pd  # requires tabulate

        rowlist = example[0]
        table_title = example[1]
        table = pd.DataFrame(rowlist[1:], columns=rowlist[0])

        if self._table_str_f == "to_markdown":
            table_str = table.to_markdown()
        elif self._table_str_f == "to_string":
            table_str = table.to_string()
        elif self._table_str_f == "to_json":
            # List of rows
            table_str = table.to_json(orient='records')
        else:
            raise ValueError(f"Unknown table string function {self._table_str_f}")

        data2prompt = f"Table title: {table_title}\n{table_str}"

        return data2prompt


class Llama3Metric(OllamaMetric):
    def postprocess_output(self, output):
        output = output.strip()
        j = json.loads(output)

        # the model often tends to produce a nested list
        annotations = j[self.annotation_key]
        if isinstance(annotations, list) and len(annotations) >= 1 and isinstance(annotations[0], list):
            j[self.annotation_key] = j[self.annotation_key][0]

        return j
