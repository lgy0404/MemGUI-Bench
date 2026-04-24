# encoding: utf-8
"""
LLM API调用模块
从config.yaml中读取API配置，支持OpenAI兼容的API
"""

import os
import sys
import base64
import time

from openai import OpenAI

# Import configuration from llm_config
from .llm_config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MODEL_PRICING,
)

# Client cache to avoid repeated creation
_client_cache = {}


def _get_client(base_url=None, api_key=None):
    """获取或创建指定配置的 OpenAI 客户端"""
    url = base_url or os.environ.get("QWEN_BASE_URL") or os.environ.get("BASE_URL") or DEFAULT_BASE_URL
    key = (
        api_key
        or os.environ.get("QWEN_API_KEY")
        or os.environ.get("M3A_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or DEFAULT_API_KEY
    )

    if not key:
        raise ValueError(
            "No API key available for AndroidWorld LLM client. "
            "Pass api_key/base_url explicitly, or set the corresponding values "
            "in config.yaml or environment variables."
        )

    cache_key = f"{url}:{key}"

    if cache_key not in _client_cache:
        _client_cache[cache_key] = OpenAI(base_url=url, api_key=key)
    return _client_cache[cache_key]


# Default client placeholder kept only for backward compatibility.
# We intentionally avoid eager client creation during import because some
# execution paths provide credentials only after argparse runs.
client = None


def extract_token_usage(usage_info):
    """Extract token usage from API response."""
    if not usage_info:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)
    total_tokens = usage_info.get("total_tokens", prompt_tokens + completion_tokens)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def calculate_api_cost(usage_info, model):
    """Calculate API cost based on token usage and model pricing."""
    if model not in MODEL_PRICING:
        return 0.0

    pricing = MODEL_PRICING[model]
    extracted_usage = extract_token_usage(usage_info)
    prompt_tokens = extracted_usage["prompt_tokens"]
    completion_tokens = extracted_usage["completion_tokens"]

    input_cost = (prompt_tokens / 1_000_000) * pricing["input_price_per_million"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output_price_per_million"]

    return input_cost + output_cost


def inference_chat_gemini_2_image(
    system_prompt,
    user_prompt,
    image1,
    image2,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
    base_url=None,
    api_key=None,
    **kwargs,  # Accept and ignore extra arguments for backward compatibility
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，并上传两张图片（文件路径）。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    model = model or DEFAULT_MODEL
    api_client = _get_client(base_url, api_key)
    
    # 从本地读取并转换图片为 Base64
    with open(image1, "rb") as f:
        image1_base64 = base64.b64encode(f.read()).decode("utf-8")

    with open(image2, "rb") as f:
        image2_base64 = base64.b64encode(f.read()).decode("utf-8")

    retry_count = 0
    while True:
        try:
            completion = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image1_base64}"},
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image2_base64}"},
                            },
                        ],
                    },
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                print("响应内容为空")
                retry_count += 1
                print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
                time.sleep(retry_delay)
                continue

        except Exception as e:
            print(f"发生异常: {str(e)}")
            retry_count += 1
            print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
            time.sleep(retry_delay)
            continue


def inference_chat_gemini_1_image(
    system_prompt,
    user_prompt,
    image1,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
    base_url=None,
    api_key=None,
    **kwargs,  # Accept and ignore extra arguments for backward compatibility
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，并上传一张图片（文件路径）。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    model = model or DEFAULT_MODEL
    api_client = _get_client(base_url, api_key)
    
    # 从本地读取并转换图片为 Base64
    with open(image1, "rb") as f:
        image1_base64 = base64.b64encode(f.read()).decode("utf-8")

    retry_count = 0
    while True:
        try:
            completion = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image1_base64}"},
                            },
                        ],
                    },
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                print("响应内容为空")
                retry_count += 1
                print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
                time.sleep(retry_delay)
                continue

        except Exception as e:
            print(f"发生异常: {str(e)}")
            retry_count += 1
            print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
            time.sleep(retry_delay)
            continue


def inference_chat_gemini_wo_image(
    system_prompt,
    user_prompt,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
    base_url=None,
    api_key=None,
    **kwargs,  # Accept and ignore extra arguments for backward compatibility
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，不传入图片。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    model = model or DEFAULT_MODEL
    api_client = _get_client(base_url, api_key)
    
    retry_count = 0
    while True:
        try:
            completion = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                print("响应内容为空")
                retry_count += 1
                print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
                time.sleep(retry_delay)
                continue

        except Exception as e:
            print(f"发生异常: {str(e)}")
            retry_count += 1
            print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
            time.sleep(retry_delay)
            continue


def inference_chat_gemini_multi_images(
    system_prompt,
    user_prompt,
    image_list,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
    base_url=None,
    api_key=None,
    max_images=None,
    **kwargs,  # Accept and ignore extra arguments for backward compatibility
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，支持传入多张图片。
    """
    model = model or DEFAULT_MODEL
    api_client = _get_client(base_url, api_key)
    
    if not image_list:
        return inference_chat_gemini_wo_image(
            system_prompt, user_prompt, max_retries, retry_delay,
            model, max_tokens, temperature, base_url, api_key
        )

    # 处理不同格式的图片列表
    processed_images = []
    for i, img in enumerate(image_list):
        if max_images is not None and i >= max_images:
            print(f"警告：根据设置的限制，最多处理{max_images}张图片，忽略剩余图片")
            break

        if isinstance(img, dict) and "image_url" in img and "url" in img["image_url"]:
            base64_data = (
                img["image_url"]["url"].split(",")[1]
                if "," in img["image_url"]["url"]
                else img["image_url"]["url"]
            )
            processed_images.append(base64_data)
        elif isinstance(img, str):
            if img.startswith("data:image"):
                base64_data = img.split(",")[1] if "," in img else img
                processed_images.append(base64_data)
            elif os.path.exists(img):
                with open(img, "rb") as f:
                    base64_data = base64.b64encode(f.read()).decode("utf-8")
                    processed_images.append(base64_data)
            else:
                print(f"警告：无法处理图片 {img}，跳过")
        else:
            print(f"警告：不支持的图片格式 {type(img)}，跳过")

    if not processed_images:
        print("警告：没有有效的图片，切换到无图片模式")
        return inference_chat_gemini_wo_image(
            system_prompt, user_prompt, max_retries, retry_delay,
            model, max_tokens, temperature, base_url, api_key
        )

    # 构建消息内容
    content = [{"type": "text", "text": user_prompt}]
    for base64_data in processed_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}
        })

    retry_count = 0
    while True:
        try:
            completion = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            response_content = completion.choices[0].message.content
            if response_content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": response_content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                print("响应内容为空")
                retry_count += 1
                print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
                time.sleep(retry_delay)
                continue

        except Exception as e:
            print(f"发生异常: {str(e)}")
            retry_count += 1
            print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
            time.sleep(retry_delay)
            continue


def inference_chat_gemini_multiturn(
    messages,
    image_paths=None,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
    base_url=None,
    api_key=None,
    **kwargs,  # Accept and ignore extra arguments for backward compatibility
):
    """
    使用 OpenAI 兼容的客户端进行多轮对话推理。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    model = model or DEFAULT_MODEL
    api_client = _get_client(base_url, api_key)
    
    # 创建消息列表的本地副本
    request_messages = []

    # 转换消息格式为OpenAI兼容格式
    for msg in messages:
        if isinstance(msg, dict):
            if "contentType" in msg:
                if msg.get("contentType") == "text":
                    if isinstance(msg.get("content"), list):
                        request_messages.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                    else:
                        request_messages.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                elif msg.get("contentType") == "image":
                    if request_messages and request_messages[-1]["role"] == "user":
                        if isinstance(request_messages[-1]["content"], str):
                            request_messages[-1]["content"] = [
                                {"type": "text", "text": request_messages[-1]["content"]}
                            ]
                        request_messages[-1]["content"].append({
                            "type": "image_url",
                            "image_url": {"url": msg["content"]}
                        })
                    else:
                        request_messages.append({
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": msg["content"]}}
                            ]
                        })
            else:
                request_messages.append(msg)
        else:
            request_messages.append({"role": "user", "content": str(msg)})

    # 收集历史图片
    historical_images = []
    for msg in messages:
        if (isinstance(msg, dict) and
            msg.get("role") == "assistant" and
            "_screenshot_base64" in msg):
            historical_images.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{msg['_screenshot_base64']}"}
            })

    # 处理额外的图片路径
    image_contents = []
    if image_paths:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        for image_path in image_paths:
            try:
                with open(image_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode("utf-8")
                image_contents.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                })
            except FileNotFoundError:
                print(f"警告：图片文件未找到: {image_path}")
            except Exception as e:
                print(f"警告：处理图片 {image_path} 时出错: {e}")

    # 找到最后一条用户消息并修改
    last_user_idx = -1
    for i in range(len(request_messages) - 1, -1, -1):
        if request_messages[i]["role"] == "user":
            last_user_idx = i
            break

    if last_user_idx >= 0:
        image_description = ""
        if historical_images:
            image_description += f"\n\nNote: The following {len(historical_images)} images are historical screenshots from previous steps."

        original_content = request_messages[last_user_idx]["content"]
        original_text = ""
        current_images = []
        if isinstance(original_content, str):
            original_text = original_content
        elif isinstance(original_content, list):
            for part in original_content:
                if part.get("type") == "text":
                    original_text = part.get("text", "")
                elif part.get("type") == "image_url":
                    current_images.append(part)

        enhanced_text = original_text + image_description
        new_content = [{"type": "text", "text": enhanced_text}] + historical_images + current_images
        request_messages[last_user_idx]["content"] = new_content

    retry_count = 0
    while True:
        try:
            completion = api_client.chat.completions.create(
                model=model,
                messages=request_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            response_content = completion.choices[0].message.content
            if response_content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": response_content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                print("响应内容为空")
                retry_count += 1
                print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
                time.sleep(retry_delay)
                continue

        except Exception as e:
            print(f"发生异常: {str(e)}")
            retry_count += 1
            print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
            time.sleep(retry_delay)
            continue
