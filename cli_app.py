import asyncio
from mcp import StdioServerParameters
from db_agent import DbAgent
from ollama_tools import ToolManager
from mcp_client import MCPClient
import json
import re
import ast
import traceback
from enum import Enum, auto

class ToolType(Enum):
    READ_QUERY = "read_query"
    LIST_TABLES= "list_tables"
    DESCRIBE_TABLE = "describe_table"

    @classmethod
    def get_param_schema(cls, tool_type, args=None):
        """setup parameter specific  schema for each tool type."""
        args = args if args is not None else ""
        if tool_type == cls.READ_QUERY:
            return {"query": args}
        elif tool_type == cls.DESCRIBE_TABLE:
            return {"table_name": args}
        elif tool_type == cls.LIST_TABLES:
            return {}
        else:
            return {}

async def execute_tool(mcp_client, tool_name, input_params=None):
        """Execute a specific MCP tool and process it's results"""
        try:
            input_params = input_params or {}
            print(f"\nExecuting {tool_name} with parameters: {input_params}")
            result = await mcp_client.call_tool(tool_name, input_params)
            await process_tool_result(result)
            return result
        except Exception as e:
            print(f"Error executing {tool_name}: {e}")
            print(traceback.format_exc())
            return None


async def process_tool_result(result):
    "Process and display called MCP tools in a consistent format."
    if hasattr(result, 'content') and result.content:
        text_content = result.content[0].text if result.content[0].text \
            else "No data returned."
        print(text_content)

        #format to json if possible
        try:
            python_obj = ast.literal_eval(text_content)
            print("\nFormatted result:")
            print(json.dumps(python_obj, indent=2))
        except (SyntaxError, ValueError):
            # If not valid Python or JSON, just show as is 
            pass
    else:
        print(result)

async def process_and_execute_tool_response(response, mcp_client):
    """Parse a response and execute the appropriate tool if suggested."""
    response_obj = response
    if isinstance(response, str) and response.strip().startswith('{') \
        and response.strip().endswith('}'):
        try:
            response_obj = json.loads(response)
        except json.JSONDecodeError:
            print("\nResponse (as text):", response)
            return

    if isinstance(response_obj, dict) and "name" in response_obj \
        and "input" in response_obj:
        try:
            tool_name = response_obj["name"]
            tool_input = response_obj["input"]
            tool_type = ToolType(tool_name)

            if tool_type == ToolType.READ_QUERY:
                params = ToolType.get_param_schema(tool_type, tool_input.get("query", ""))
            elif tool_type == ToolType.DESCRIBE_TABLE:
                params = ToolType.get_param_schema(tool_type, tool_input.get("table_name", ""))
            else:
                params = ToolType.get_param_schema(tool_type)

            return await execute_tool(mcp_client, tool_type.value, params)

        except ValueError:
            print(f"\nUnknown tool: {response_obj['name']}")
            print(f"\nResponse:", response_obj)
    else:
        print("\nResponse:", response_obj)

async def handle_direct_command(command, args, mcp_client):
    """Handle direct commands like read_query, list_tables, and describe-table using the ToolType enum."""
    try:
        tool_type = next((t for t in ToolType if t.value == command), None)

        if tool_type:
            params = ToolType.get_param_schema(tool_type, args)
            await execute_tool(mcp_client, tool_type.value, params)
        else:
            print(f"Unknown command: {command}")
    except Exception as e:
        print("error handling command:", e)
        print(traceback.format_exc())


async def main():
    """
    Main function that sets up and runs an interactive AI agent with tool integration.
    The agent can process user prompts and utilize registered tools to perform tasks with Ollama.
    """
    # Initialize model configuration for Ollama
    model_id = "llama3.1"  # Using llama3.1 model in Ollama
    # model_id = "deepseek-r1"
    
    # Set up the agent and tool manager
    agent = DbAgent(model_id)
    agent.tools = ToolManager()

    # Define the agent's behavior through system prompt with specific tool usage instructions
    agent.system_prompt = """You are a helpful database assistant that can query a SQLite Jeopardy database.

The database contains information about Jeopardy categories, questions, and games.

When a user asks for information that requires querying the database, you should:
1. Determine the appropriate SQL query
2. Use the read_query tool to execute it
3. Format and explain the results

When you need to use the database tools, respond with a JSON block in the appropriate format:

For SQL queries:
```json
{
  "name": "read_query",
  "input": {
    "query": "YOUR SQL QUERY HERE"
  }
}
```

For listing available tables:
```json
{
  "name": "list_tables",
  "input": {}
}
```

For describing table schema:
```json
{
  "name": "describe_table",
  "input": {
    "table_name": "TABLE_NAME_HERE"
  }
}
```

Available tools:
- read_query: Executes a SQL query against the database
- list_tables: Lists all tables in the database
- describe_table: Describe the schema of a specific table

Always ensure your SQL queries are valid SQLite syntax. For example, if a user asks about categories, you should query the 'categories' table.
Sample tables in the database:

categories: Contains category_id, season_id, game_id, round_name, category_name
(likely other tables for questions, answers, contestants, etc.)

Remember to always use the query parameter, not sql."""

    server_params = StdioServerParameters(
        command="/Users/tomlegnard/.local/bin/uv",
        args=["--directory", "/Users/tomlegnard/repos/mcp/servers/src/sqlite", "run", "mcp-server-sqlite", "--db-path", "/Users/tomlegnard/repos/answer-there/jeopardy.db"],
        env=None
    )

    # Initialize MCP client with server parameters
    async with MCPClient(server_params) as mcp_client:

        tools = await mcp_client.get_available_tools()
        
        print("Available tools:")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
            print(f"  Input schema: {tool.inputSchema}")

            agent.tools.register_tool(
                name=tool.name,
                func=mcp_client.call_tool,
                description=tool.description,
                input_schema=tool.inputSchema
            )


        print("\nDatabase assistant ready! Type SQL queries or questions about your database.")
        print("Example: 'read_query select * from sqlite_master;'")
        print("Additional commands: 'list_tables', 'describe_table <table_name>'")
        print("You may also direct the assistant to find specific data points and it will attemp to write and run the SQl for you!")
        
        while True:
            try:

                user_prompt = input("\nEnter your prompt (or 'quit' to exit): ")
                if user_prompt.lower() in ['quit', 'exit', 'q']:
                    break

                command_match = re.match(r'(read_query|list_tables|describe_table)\s*(.*)', user_prompt.strip())
                if command_match:
                    command, args = command_match.groups()
                    await handle_direct_command(command, args.strip(), mcp_client)

                else:
                    # Process natural language prompt through the agent
                    print(f"\nProcessing: '{user_prompt}'")
                    try:
                        response = await agent.invoke_with_prompt(user_prompt)
                        print(f"response before processing: {response}")
                        
                        # Handle empty response
                        if not response:
                            print("Received empty response from agent.")
                            continue

                        await process_and_execute_tool_response(response, mcp_client)

                    except Exception as e:
                        print(f"\nError processing prompt: {e}")
                        print(f"response type: {type(response) if 'response' in locals() else 'No response'}")
                        print(f"response value: {response if 'response' in locals() else 'No response'}")
                        print(traceback.format_exc())  # Print full traceback
                        print("\nTry using a query directly with 'read_query <your SQL>'")

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"\nError occurred: {e}")
                print(traceback.format_exc())
                print("Try using a query directly with 'read_query <your SQL>'")

if __name__ == "__main__":
    asyncio.run(main())


