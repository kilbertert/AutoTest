# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pydantic import BaseModel, Field
import json


def api_analysis_prompt(task_info: str = "") -> str:
    """
    Generates a prompt to analyze API response and determine if it satisfies the given task information.

    Args:
        task_info (str): The specific task to evaluate based on the API response.

    Returns:
        str: A formatted prompt for the task.
    """
    return f"""
        ### **Task:**
        You are provided with an API response.
        Your task is to analyze the response and determine if it satisfies the following requirement: {task_info}.

        ### **Instructions:**
        1. Analyze the API response for indicators that are relevant to the task. Look for:
        - Presence or absence of specific data fields mentioned in the task.
        - Expected values or data patterns that match the requirement.
        - Status codes, error messages, or schema validation results.
        2. Based on your analysis, decide whether the API response satisfies the task requirement.
        3. Make sure your explanation clearly states the observed facts that led to your conclusion.

        ### **Note:**
        Focus your analysis on aspects related to the task requirement, regardless of the API endpoint.
        """


class ApiTaskResponse(BaseModel):
    """
    Response model for API task evaluation.

    Attributes:
        result (bool): Indicates whether the task is satisfied.
        reason (str): Explanation of the evaluation result.
    """

    result: bool = Field(..., description="Indicates whether the task is satisfied")
    reason: str = Field(..., description="Explanation of the evaluation result")

    @classmethod
    def get_json_schema(cls) -> str:
        """return json schema for the response model"""
        return json.dumps(cls.model_json_schema(), indent=2)

    @classmethod
    def get_format_description(cls) -> str:
        """return concise format description for prompt"""
        schema = cls.model_json_schema()
        properties = schema.get("properties", {})

        format_desc = "{\n"
        for field_name, field_info in properties.items():
            field_type = field_info.get("type", "any")
            description = field_info.get("description", "")
            format_desc += f'  "{field_name}": {field_type}  // {description}\n'
        format_desc += "}"

        return format_desc

    @classmethod
    def get_example_json(cls) -> str:
        """return example JSON"""
        example = {"result": True, "reason": "The API response contains the expected data and satisfies the task requirements."}
        return json.dumps(example, indent=2)

    @classmethod
    def get_prompt_format(cls) -> str:
        """return complete prompt format description"""
        return f"""
            Response must be in strict JSON format with the following structure:

            {cls.get_format_description()}

            Example:
            {cls.get_example_json()}

            Required fields:
            - result: boolean indicating if task is satisfied
            - reason: string explanation of the evaluation result
            """


def api_code_gen_prompt(scenario_text: str, feature_file: str) -> str:
    """
    Generates a prompt for code generation based on BDD scenario.

    Args:
        scenario_text: The BDD scenario text
        feature_file: Path to the feature file

    Returns:
        str: Formatted prompt for code generation
    """
    return f"""
Please generate Python pytest + httpx test code based on the following BDD scenario:

# Feature File: {feature_file}

# Scenario:
{scenario_text}

## Requirements:
1. Use httpx.Client for HTTP requests
2. Include proper assertions for status code, response body, and headers
3. Extract variables when needed (e.g., extract token from login response)
4. Follow clean code style from existing examples
5. Use pytest fixture for API client setup
"""
