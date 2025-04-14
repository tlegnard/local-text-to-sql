import asyncio
from mcp import StdioServerParameters
from db_agent import DbAgent
from ollama_tools import ToolManager
from mcp_client import MCPClient
import json
import re
import ast
import traceback  # Added for better error tracing

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

async def mcp_read_query(mcp_client, sql):
    try:
        result = await mcp_client.call_tool("read_query", {"query": sql})
        print("\nQuery result:")
        # print(result)  # This might be printing a complex object that doesn't format well
        await process_tool_result(result)

    except Exception as e:
        print(f"SQL query error: {e}")
        print(traceback.format_exc())  # Print stack trace for debugging


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

    # Create server parameters for SQLite configuration
    server_params = StdioServerParameters(
        command="/Users/tomlegnard/.local/bin/uv",
        args=["--directory", "/Users/tomlegnard/repos/mcp/servers/src/sqlite", "run", "mcp-server-sqlite", "--db-path", "/Users/tomlegnard/repos/answer-there/jeopardy.db"],
        env=None
    )

    # Initialize MCP client with server parameters
    async with MCPClient(server_params) as mcp_client:

        # Fetch available tools from the MCP client
        tools = await mcp_client.get_available_tools()
        
        print("Available tools:")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
            print(f"  Input schema: {tool.inputSchema}")
            
            # Register the tool with the agent
            agent.tools.register_tool(
                name=tool.name,
                func=mcp_client.call_tool,
                description=tool.description,
                input_schema=tool.inputSchema
            )

        # Start interactive prompt loop
        print("\nDatabase assistant ready! Type SQL queries or questions about your database.")
        print("Example: 'read_query select * from sqlite_master;'")
        print("Additional commands: 'list_tables', 'describe-table <table_name>'")
        
        while True:
            try:
                # Get user input and check for exit commands
                user_prompt = input("\nEnter your prompt (or 'quit' to exit): ")
                if user_prompt.lower() in ['quit', 'exit', 'q']:
                    break
                
                # Special case for direct SQL queries
                if user_prompt.strip().startswith('read_query '):
                    sql = user_prompt.replace('read_query ', '', 1).strip()
                    # Remove quotes if they're present
                    if (sql.startswith("'") and sql.endswith("'")) or (sql.startswith('"') and sql.endswith('"')):
                        sql = sql[1:-1]
                    
                    # Execute direct SQL query
                    await mcp_read_query(mcp_client, sql)
                
                # Special case for direct list_tables command
                elif user_prompt.strip() == 'list_tables':
                    try:
                        result = await mcp_client.call_tool("list_tables", {})
                        print("\nAvailable tables:")
                        await process_tool_result(result)
                    except Exception as e:
                        print(f"Error listing tables: {e}")
                        print(traceback.format_exc())
                
                # Special case for direct describe-table command
                elif user_prompt.strip().startswith('describe-table '):
                    table_name = user_prompt.replace('describe-table ', '', 1).strip()
                    try:
                        result = await mcp_client.call_tool("describe_table", {"table_name": table_name})
                        print(f"\nSchema for table: {table_name}")
                        await process_tool_result(result)
                    except Exception as e:
                        print(f"Error describing table: {e}")
                        print(traceback.format_exc())
                    
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
                        
                        # Handle different response types
                        if isinstance(response, dict):
                            # If it's already a dictionary, process it directly
                            if "name" in response and response["name"] == "read_query" and "input" in response:
                                print(f"Executing query: {response['input'].get('query', '')}")
                                await mcp_read_query(mcp_client, response["input"].get("query", ""))
                            elif "name" in response and response["name"] == "list_tables":
                                print("Listing all tables in the database:")
                                result = await mcp_client.call_tool("list_tables", {})
                                await process_tool_result(result)
                            elif "name" in response and response["name"] == "describe_table":
                                print(f"Describing table: {response['input'].get('table_name', 'Unknown')}")
                                result = await mcp_client.call_tool("describe_table", {"table_name": response['input'].get('table_name', '')})
                                await process_tool_result(result)
                            else:
                                print("\nResponse:", response)
                        
                        elif isinstance(response, str):
                            # Try to parse as JSON if it looks like a JSON string
                            if response.strip().startswith('{') and response.strip().endswith('}'):
                                try:
                                    response_obj = json.loads(response)
                                    print(f"Response parsed as JSON: {response_obj}")
                                    
                                    if "name" in response_obj and response_obj["name"] == "read_query" and "input" in response_obj:
                                        await mcp_read_query(mcp_client, response_obj["input"].get("query", ""))
                                    elif "name" in response_obj and response_obj["name"] == "list_tables":
                                        print("Listing all tables in the database:")
                                        result = await mcp_client.call_tool("list_tables", {})
                                        await process_tool_result(result)
                                    elif "name" in response_obj and response_obj["name"] == "describe_table":
                                        print(f"Describing table: {response_obj['input'].get('table_name', 'Unknown')}")
                                        result = await mcp_client.call_tool("describe_table", {"table_name": response_obj['input'].get('table_name', '')})
                                        await process_tool_result(result)
                                    else:
                                        print("\nResponse:", response_obj)
                                except json.JSONDecodeError:
                                    # If it's not valid JSON, just show the text
                                    print("\nResponse (as text):", response)
                            else:
                                # It's a regular text response
                                print("\nResponse:", response)
                        else:
                            print(f"\nUnexpected response type: {type(response)}")
                            print("\nResponse:", response)
                        
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
    # Run the async main function
    asyncio.run(main())


