import json
import os
import re
import base64
import uuid
import requests
import copy
from typing import Optional, Tuple, Dict, List, Any

from openai import OpenAI
from google import genai
from google.genai import types
from loguru import logger

import dotenv

dotenv.load_dotenv()

class LLMContentGenerator:
    """
    Lớp xử lý gọi các API LLM (OpenAI, Gemini) để sinh nội dung
    """
    
    def __call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        retry: int = 3,
        json: bool = True,
        media_urls: List[str] = [],
        temperature: float = 0.0,
        can_empty: bool = False,
    ) -> Tuple[bool, Optional[Any], Optional[str], Optional[Dict[str, int]]]:
        """
        Gọi OpenAI API để sinh nội dung
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            model: Tên model OpenAI
            retry: Số lần thử lại nếu lỗi
            json: Có trả về dạng JSON hay không
            media_urls: Danh sách đường dẫn đến media
            temperature: Độ ngẫu nhiên của câu trả lời
            
        Returns:
            Tuple gồm:
            - is_success: Có thành công hay không
            - result: Kết quả trả về
            - error: Lỗi nếu có
            - tokens_count: Số token sử dụng
        """
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            show_log(message=f"__call_openai", level="info")
            
            if media_urls:
                content_parts = [{"type": "text", "text": user_prompt}]
                
                for image_path in media_urls:
                    base64_image = encode_image(image_path)
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    })
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_parts}
                ]
                
                if json:
                    response = client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=messages,
                        temperature=temperature,
                        timeout=60 * 10  # 10 minutes
                    )
                    result = convert_prompt_to_json(response.choices[0].message.content)
                else:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        timeout=60 * 10  # 10 minutes
                    )
                    result = response.choices[0].message.content
                
                tokens_count = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]

                if json:
                    response = client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=messages,
                        temperature=temperature,
                        timeout=60 * 5  # 5 minutes
                    )
                    result = convert_prompt_to_json(response.choices[0].message.content)
                else:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        timeout=60 * 5  # 5 minutes
                    )
                    result = response.choices[0].message.content
                
                tokens_count = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
                
            if len(result) == 0:
                if can_empty:
                    return True, [], None, tokens_count
                else:
                    raise Exception("Empty response")
                
            return True, result, None, tokens_count

        except Exception as ex:
            if retry <= 0:
                show_log(message=f"Fail to call __call_openai with ex: {ex}, retry: {retry}", level="error")
                return False, None, str(ex), None

            show_log(message=f"__call_openai -> Retry {retry}", level="error")
            retry -= 1
            return self.__call_openai(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                retry=retry,
                json=json,
                media_urls=media_urls,
                temperature=temperature
            )

    def __call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        retry: int = 3,
        json: bool = False,
        media_urls: List[str] = [],
        temperature: float = 0.0,
        top_k: int = 40,
        top_p: float = 0.95,
        thinking_budget: int = 0,
        properties: Optional[Dict] = None,
        can_empty: bool = False,
    ) -> Tuple[bool, Optional[Any], Optional[str], Optional[Dict[str, int]]]:
        """
        Gọi Gemini API để sinh nội dung
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            model: Tên model Gemini
            retry: Số lần thử lại nếu lỗi
            json: Có trả về dạng JSON hay không
            media_urls: Danh sách đường dẫn đến media
            temperature: Độ ngẫu nhiên của câu trả lời
            top_k: Tham số top_k
            top_p: Tham số top_p
            thinking_budget: Ngân sách suy nghĩ
            keys: Danh sách các key
        Returns:
            Tuple gồm:
            - is_success: Có thành công hay không
            - result: Kết quả trả về
            - error: Lỗi nếu có
            - tokens_count: Số token sử dụng
        """
        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            files = []
            for url in media_urls:
                files.append(self.upload_to_gemini(client, url))

            show_log(message=f"__call_gemini", level="info")
            
            parts = [types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type) for file in files]
            parts.append(types.Part.from_text(text=user_prompt))
            contents = [
                types.Content(
                    role="user",
                    parts=parts,
                ),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget > 0 else None,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE",
                    ),
                ],
                response_mime_type="application/json" if json else "text/plain",
                response_schema=properties,
                system_instruction=[
                    types.Part.from_text(text=system_prompt),
                ],
            )
            
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_content_config
            )
            
            token_count = {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count + response.usage_metadata.thoughts_token_count if thinking_budget > 0 else response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count
            }
            
            if json:
                result = convert_prompt_to_json(response.text)
            else:
                result = response.text
                
            if len(result) == 0 or not result:
                if can_empty:
                    return True, [], None, token_count
                else:
                    raise Exception("Empty response")
            
            return True, result, None, token_count

        except Exception as ex:
            if retry <= 0:
                show_log(message=f"Fail to call __call_gemini with ex: {ex}, retry: {retry}", level="error")
                return False, None, str(ex), None
                
            show_log(message=f"__call_gemini -> Retry {retry}", level="error")
            retry -= 1
            return self.__call_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                retry=retry,
                json=json,
                media_urls=media_urls,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                thinking_budget=thinking_budget,
                properties=properties
            )

    def __stream_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        media_urls: List[str] = [],
        temperature: float = 0.0
    ):
        """
        Stream nội dung từ OpenAI API
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            model: Tên model OpenAI
            media_urls: Danh sách đường dẫn đến media
            temperature: Độ ngẫu nhiên của câu trả lời
            
        Yields:
            Từng phần nội dung được sinh ra
        """
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            show_log(message=f"__stream_openai", level="info")
            
            if media_urls:
                content_parts = [{"type": "text", "text": user_prompt}]
                
                for image_path in media_urls:
                    base64_image = encode_image(image_path)
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    })
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_parts}
                ]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                stream=True
            )
            
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        except Exception as ex:
            show_log(message=f"Error in OpenAI streaming: {ex}", level="error")
            yield f"Error: {str(ex)}"
            
    def __stream_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        media_urls: List[str] = [],
        temperature: float = 0.0,
        top_k: int = 40,
        top_p: float = 0.95
    ):
        """
        Stream nội dung từ Gemini API
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            model: Tên model Gemini
            media_urls: Danh sách đường dẫn đến media
            temperature: Độ ngẫu nhiên của câu trả lời
            top_k: Tham số top_k
            top_p: Tham số top_p
            
        Yields:
            Từng phần nội dung được sinh ra
        """
        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            files = []
            for url in media_urls:
                files.append(self.upload_to_gemini(client, url))

            show_log(message=f"__stream_gemini", level="info")
            
            parts = [types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type) for file in files]
            parts.append(types.Part.from_text(text=user_prompt))
            contents = [
                types.Content(
                    role="user",
                    parts=parts,
                ),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE",
                    ),
                ],
                system_instruction=[
                    types.Part.from_text(text=system_prompt),
                ],
            )
            
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                yield chunk.text
                
        except Exception as ex:
            show_log(message=f"Error in Gemini streaming: {ex}", level="error")
            yield f"Error: {str(ex)}"

    def completion(
        self,
        system_prompt: str,
        user_prompt: str,
        providers: List[Dict],
        json: bool = False,
        media_urls: List[str] = [],
        ai_metadata: Dict = {},
        properties: Optional[Dict] = None,
        can_empty: bool = False,
    ) -> Tuple[Optional[Any], Optional[Dict[str, int]]]:
        """
        Sinh nội dung từ các provider (OpenAI, Gemini)
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            providers: Danh sách các provider và cấu hình
            json: Có trả về dạng JSON hay không
            media_urls: Danh sách đường dẫn đến media
            ai_metadata: Metadata cho AI
            properties: Cấu hình cho AI
            can_empty: Kết quả có thể rỗng hay không
        Returns:
            Tuple gồm:
            - response: Kết quả trả về
            - token_count: Số token sử dụng
        """
        # remove <|endofprompt|>, <|endoftext|> in user prompt
        user_prompt = user_prompt.replace("<|endofprompt|>", "endofprompt").replace("<|endoftext|>", "endoftext")

        if not providers:
            raise Exception("Providers is empty")
            
        try:
            is_success, response, error = False, None, None
            for provider in providers:
                if provider["name"] == "openai":
                    is_success, response, error, token_count = self.__call_openai(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=provider["model"],
                        retry=provider["retry"],
                        json=json,
                        media_urls=media_urls,
                        temperature=provider.get("temperature", 0.0),
                        can_empty=can_empty
                    )
                    if is_success:
                        try:
                            ai_metadata['workflow'].append(f'generate_with_{provider["model"]}')
                        except Exception as e:
                            pass
                        return response, token_count

                if provider["name"] == "gemini":
                    is_success, response, error, token_count = self.__call_gemini(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=provider["model"],
                        retry=provider["retry"],
                        json=json,
                        media_urls=media_urls,
                        temperature=provider.get("temperature", 0.0),
                        top_k=provider.get("top_k", 40),
                        top_p=provider.get("top_p", 0.95),
                        thinking_budget=provider.get("thinking_budget", 0),
                        properties=properties,
                        can_empty=can_empty
                    )
                    if is_success:
                        try:
                            ai_metadata['workflow'].append(f'generate_with_{provider["model"]}')
                        except Exception as e:
                            pass
                        return response, token_count
                        
            if not is_success:
                raise Exception(error)

            return response, token_count
            
        except Exception as ex:
            show_log(message=ex, level="error")
            return None, None

    def stream_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        providers: List[Dict],
        media_urls: List[str] = [],
        ai_metadata: Dict = {},
    ):
        """
        Stream nội dung từ các provider (OpenAI, Gemini)
        
        Args:
            system_prompt: Prompt hệ thống
            user_prompt: Prompt người dùng
            providers: Danh sách các provider và cấu hình
            media_urls: Danh sách đường dẫn đến media
            ai_metadata: Metadata cho AI
            
        Yields:
            Từng phần nội dung được sinh ra
        """
        # remove <|endofprompt|>, <|endoftext|> in user prompt
        user_prompt = user_prompt.replace("<|endofprompt|>", "endofprompt").replace("<|endoftext|>", "endoftext")

        if not providers:
            raise Exception("Providers is empty")
            
        try:
            for provider in providers:
                try:
                    if provider["name"] == "openai":
                        try:
                            ai_metadata['workflow'].append(f'stream_with_{provider["model"]}')
                        except Exception as e:
                            pass
                            
                        for chunk in self.__stream_openai(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=provider["model"],
                            media_urls=media_urls,
                            temperature=provider.get("temperature", 0.0)
                        ):
                            yield chunk
                        return
                        
                    if provider["name"] == "gemini":
                        try:
                            ai_metadata['workflow'].append(f'stream_with_{provider["model"]}')
                        except Exception as e:
                            pass
                            
                        for chunk in self.__stream_gemini(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=provider["model"],
                            media_urls=media_urls,
                            temperature=provider.get("temperature", 0.0),
                            top_k=provider.get("top_k", 40),
                            top_p=provider.get("top_p", 0.95)
                        ):
                            yield chunk
                        return
                        
                except Exception as ex:
                    show_log(message=f"Error with provider {provider['name']}: {ex}", level="error")
                    continue
                    
            raise Exception("All providers failed")
            
        except Exception as ex:
            show_log(message=ex, level="error")
            yield f"Error: {str(ex)}"

    def upload_to_gemini(self, client: genai.Client, url: str) -> Any:
        """
        Upload file lên Gemini
        
        Args:
            client: Gemini client
            url: Đường dẫn đến file
            
        Returns:
            File đã upload
        """
        try:
            if url.startswith("http"):
                file_data = requests.get(url).content
                temp_filename = f"temp_{uuid.uuid4()}.{url.split('.')[-1]}"
                with open(temp_filename, 'wb') as temp_file:
                    temp_file.write(file_data)
            else:
                temp_filename = url
            
            file = client.files.upload(file=temp_filename)
            show_log(message=f"Uploaded file as: {file.uri}", level="debug")
            return file
            
        except Exception as ex:
            show_log(message=f"Error uploading file to Gemini: {ex}", level="error")
            raise ex


def convert_prompt_to_json(presentation_json: str) -> Dict:
    """
    Chuyển đổi prompt thành JSON
    
    Args:
        presentation_json: Chuỗi JSON cần chuyển đổi
        
    Returns:
        Dict chứa dữ liệu JSON
    """
    try:
        # Find the start of the JSON content
        start_marker = '```json'
        start_index = presentation_json.find(start_marker)

        if start_index != -1:
            start_index += len(start_marker)  # Move past the '```json'

            # Find the end of the JSON content
            end_index = presentation_json.find('', start_index)

            if end_index != -1:
                # Extract the JSON content
                json_content = presentation_json[start_index:end_index].strip()
            else:
                json_content = presentation_json[start_index:].strip()

            # Convert the string to a JSON object
            return json.loads(json_content)
        else:
            return json.loads(presentation_json)
            
    except json.JSONDecodeError as ex:
        try:
            # First attempt our current regex-based fix
            pattern = r'",.*?[^\\]($|\n)'
            lines = presentation_json.split('\n')
            for i, line in enumerate(lines):
                # Find unterminated strings and attempt to close them
                matches = re.finditer(pattern, line, re.DOTALL)
                for match in matches:
                    if match.group().endswith(('\n', '"')):
                        continue
                    fixed_string = match.group()[:-1] + '"\n'
                    line = line[:match.start()] + fixed_string + line[match.end():]
                    lines[i] = line

            fixed_json_string = '\n'.join(lines)
            try:
                # Try parsing again after the fix
                return json.loads(fixed_json_string)
            except json.JSONDecodeError:
                # If still failing, use json_repair
                from json_repair import repair_json
                show_log(f"Attempting to repair JSON with json_repair", level="info")
                repaired_json = repair_json(presentation_json)
                return json.loads(repaired_json)
                
        except Exception as e:
            # If all repair attempts fail
            logger.error(f"Failed to repair JSON: {e}")
            raise e


def encode_image(image_path: str) -> str:
    """
    Mã hóa hình ảnh thành base64
    
    Args:
        image_path: Đường dẫn đến hình ảnh
        
    Returns:
        Chuỗi base64 của hình ảnh
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def show_log(message: str, level: str = "info") -> None:
    """
    Hiển thị log
    
    Args:
        message: Nội dung log
        level: Cấp độ log
    """
    if level == "debug" and os.getenv('DEBUG'):
        logger.debug(str(message))
    elif level == "error":
        logger.error(str(message))
    else:
        logger.info(str(message))



