import json
import re
import requests

class DbAgent:
    def __init__(self, model_id, base_url='http://localhost:11434', system_prompt='You are a helpful assistant.'):
        self.model_id = model_id
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.messages = []  # Keep this for message history tracking
        self.tools = None
        self.response_output_tags = []

    async def invoke_with_prompt(self, prompt):
        return await self.invoke([{"text": prompt}])

    async def invoke(self, content):
        print(f"content before json dump {content}")  # Added for debugging
        print(f"User: {json.dumps(content, indent=2)}")
        print(f"CONTENT 0 {content[0]}")
        
        # Store in message history (for tracking purposes)
        if isinstance(content[0], dict) and 'text' in content[0]:
            # Regular user message
            self.messages.append(
                {
                    "role": "user", 
                    "content": content[0]['text']
                }
            )
        else:
            # Tool result message
            tool_content = ""
            for item in content:
                if 'toolResult' in item and 'content' in item['toolResult']:
                    for content_item in item['toolResult']['content']:
                        if 'text' in content_item:
                            tool_content += content_item['text'] + "\n"
            
            self.messages.append(
                {
                    "role": "system",
                    "content": f"Tool execution result: {tool_content}"
                }
            )

        # Get response from Ollama but only using the latest user message
        response = self._get_ollama_response()
        print(f"Agent: {json.dumps(response, indent=2)}")

        # Store assistant's response in our message history
        response_text = response.get('output', {}).get('message', {}).get('content', [{}])[0].get('text', '')
        if response_text:
            self.messages.append({
                "role": "assistant",
                "content": response_text
            })

        return await self._handle_response(response)

    def _get_ollama_response(self):
            """
            Send request to Ollama API with only the system prompt and latest user message
            """
            # Prepare messages for Ollama API - just system prompt and latest user message
            ollama_messages = []
            
            # First add system prompt
            ollama_messages.append({
                "role": "system",
                "content": self.system_prompt
            })
            
            # Find the latest user message
            latest_user_message = None
            for msg in reversed(self.messages):
                if msg["role"] == "user":
                    latest_user_message = msg
                    break
            
            # Add only the latest user message if found
            if latest_user_message:
                ollama_messages.append({
                    "role": "user",
                    "content": latest_user_message["content"]
                })
            
            print(f"============\n Full message history: {self.messages} \n +++++++++\n")
            print(f"Sending only the system prompt and latest user message to Ollama")
            
            # Add tool definitions if available
            tool_defs = None
            if self.tools:
                tool_defs = self.tools.get_tools_ollama_format()
                
            print(f"OLLAMA MESSAGES: \n\n {ollama_messages} \n\n")
            
            # Make API request to Ollama
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": self.model_id,
                "messages": ollama_messages,
                "stream": False
            }
            
            # Add temperature only if supported
            payload["options"] = {"temperature": 0.7}
            
            # Add tools if available
            if tool_defs:
                payload["tools"] = tool_defs
            
            try:
                print(f"Sending to Ollama API: {json.dumps(payload, indent=2)}")
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                
                # Format response to match the expected structure from AWS Bedrock
                formatted_response = {
                    "stopReason": "end_turn",  # Default stop reason
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "text": result.get("message", {}).get("content", "")
                                }
                            ]
                        }
                    }
                }
                
                # Check if the response contains a tool call
                content = result.get("message", {}).get("content", "")
                if "tool_use" in content.lower() or "```json" in content:
                    # Try to extract tool call from the response
                    formatted_response["stopReason"] = "tool_use"
                    
                    # Extract the JSON tool call
                    json_pattern = r'```json\s*(.*?)\s*```'
                    match = re.search(json_pattern, content, re.DOTALL)
                    if match:
                        try:
                            tool_data = json.loads(match.group(1))
                            formatted_response["output"]["message"]["content"] = [
                                {
                                    "toolUse": {
                                        "toolUseId": "tool-1",  # Generate a unique ID in a real implementation
                                        "name": tool_data.get("name", ""),
                                        "input": tool_data.get("input", {})
                                    }
                                }
                            ]
                        except json.JSONDecodeError as e:
                            # Fallback if JSON parsing fails
                            print(f"JSON decode error: {e}")
                    
                return formatted_response
                
            except requests.RequestException as e:
                print(f"Request error: {str(e)}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    print(f"Response text: {e.response.text}")
                raise ValueError(f"Ollama API request failed: {str(e)}")

    async def _handle_response(self, response):
        print(response)
        response_text = response.get('output', {}).get('message', {}).get('content', [{}])[0].get('text', '')
        
        # If response is empty, generate a default query for the table mentioned in the last user message
        if not response_text.strip():
            print("Received empty response from LLM, generating default query based on user request")
            
            # Get the last user message
            last_user_message = None
            for msg in reversed(self.messages):
                if msg["role"] == "user":
                    last_user_message = msg["content"]
                    break
            print(f"LAST USER MESSAGE : {last_user_message}")
            if last_user_message:
                # Simple parsing to extract table name and type of query
                lower_msg = last_user_message.lower()
                
                # Check if user is asking for a list of tables
                if "list tables" in lower_msg or "show tables" in lower_msg or "what tables" in lower_msg:
                    return {
                        "name": "list_tables",
                        "input": {}
                    }
                
                # Check if user is asking to describe a table
                table_match = re.search(r'describe\s+table\s+(\w+)', lower_msg)
                if table_match:
                    table_name = table_match.group(1)
                    return {
                        "name": "describe_table",
                        "input": {
                            "table_name": table_name
                        }
                    }
                
                # Otherwise try to extract table name for regular query
                table_match = re.search(r'from\s+the\s+(\w+)', lower_msg)
                table_name = table_match.group(1) if table_match else None
                
                if table_name:
                    # Create a default query for this table
                    limit = 10
                    if "contestant" in table_name or "contestant" in lower_msg:
                        default_query = f"SELECT * FROM contestants LIMIT {limit}"
                    else:
                        default_query = f"SELECT * FROM {table_name} LIMIT {limit}"
                    
                    # Create a default tool response
                    return {
                        "name": "read_query",
                        "input": {
                            "query": default_query
                        }
                    }
        
        # Check stop reason for further processing
        stop_reason = response['stopReason']
        
        if stop_reason in ['end_turn', 'stop_sequence']:
            # Check if the text response contains a command to list tables
            if response_text and ("list tables" in response_text.lower() or "show tables" in response_text.lower()):
                return {
                    "name": "list_tables",
                    "input": {}
                }
            
            # Check if the text response contains a command to describe a table
            table_match = re.search(r'describe\s+table\s+(\w+)', response_text.lower())
            if table_match:
                table_name = table_match.group(1)
                return {
                    "name": "describe_table",
                    "input": {
                        "table_name": table_name
                    }
                }
            
            # Return the text directly
            return response_text

        elif stop_reason == 'tool_use':
            try:
                # Extract tool use details from response
                tool_response = []
                for content_item in response['output']['message']['content']:
                    if 'toolUse' in content_item:
                        tool_request = {
                            "toolUseId": content_item['toolUse']['toolUseId'],
                            "name": content_item['toolUse']['name'],
                            "input": content_item['toolUse']['input']
                        }
                        
                        # Handle list_tables tool specifically
                        if tool_request["name"] == "list_tables":
                            return {
                                "name": "list_tables",
                                "input": tool_request["input"] if tool_request["input"] else {}
                            }
                        
                        # Handle describe_table tool
                        if tool_request["name"] == "describe_table":
                            return {
                                "name": "describe_table",
                                "input": {
                                    "table_name": tool_request["input"].get("table_name", "")
                                }
                            }
                        
                        # Handle read_query tool
                        if tool_request["name"] == "read_query" and "sql" in tool_request["input"]:
                            # Convert "sql" parameter to "query" parameter
                            sql_query = tool_request["input"].pop("sql")
                            tool_request["input"]["query"] = sql_query

                        print(f"Executing tool: {tool_request['name']} with input: {tool_request['input']}")
                        tool_result = await self.tools.execute_tool(tool_request)
                        print(f"Tool result: {tool_result}")
                        tool_response.append({'toolResult': tool_result})
                
                # Instead of recursively calling invoke again, directly return the tool call info
                return {
                    "name": tool_request["name"],
                    "input": tool_request["input"]
                }
                
            except KeyError as e:
                raise ValueError(f"Missing required tool use field: {e}")
            except Exception as e:
                raise ValueError(f"Failed to execute tool: {e}")

        elif stop_reason == 'max_tokens':
            # Hit token limit
            continuation = await self.invoke_with_prompt('Please continue.')
            return continuation

        else:
            raise ValueError(f"Unknown stop reason: {stop_reason}")