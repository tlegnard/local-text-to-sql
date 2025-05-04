import streamlit as st
import asyncio
import json
import re
from mcp import StdioServerParameters
from mcp_client import MCPClient
import ast
from enum import Enum

# Define tool types as in your original code
class ToolType(Enum):
    READ_QUERY = "read_query"
    LIST_TABLES = "list_tables"
    DESCRIBE_TABLE = "describe_table"

    @classmethod
    def get_param_schema(cls, tool_type, args=None):
        """Setup parameter specific schema for each tool type."""
        args = args if args is not None else ""
        if tool_type == cls.READ_QUERY:
            return {"query": args}
        elif tool_type == cls.DESCRIBE_TABLE:
            return {"table_name": args}
        elif tool_type == cls.LIST_TABLES:
            return {}
        else:
            return {}

# Function to run async code in Streamlit
def run_async(coroutine):
    return asyncio.run(coroutine)

# Function to set up MCP client
async def setup_mcp_client():
    # TODO: Make these parameters configurable via app settings
    server_params = StdioServerParameters(
        command="/Users/tomlegnard/.local/bin/uv",
        args=["--directory", "/Users/tomlegnard/repos/mcp/servers/src/sqlite", "run", "mcp-server-sqlite", "--db-path", "/Users/tomlegnard/repos/answer-there/jeopardy.db"],
        env=None
    )
    
    return MCPClient(server_params)

# Function to process and format tool results
def format_tool_result(result):
    if not result or not hasattr(result, 'content'):
        return "No data returned."
    
    text_content = result.content[0].text if result.content[0].text else "No data returned."
    
    # Try to parse as Python object for better formatting
    try:
        python_obj = ast.literal_eval(text_content)
        return json.dumps(python_obj, indent=2)
    except (SyntaxError, ValueError):
        # If not valid Python or JSON, just return as is
        return text_content

# Function to execute a tool
async def execute_tool(mcp_client, tool_name, input_params=None):
    try:
        input_params = input_params or {}
        result = await mcp_client.call_tool(tool_name, input_params)
        return result
    except Exception as e:
        return f"Error executing {tool_name}: {e}"

# Function to handle direct command
async def handle_command(command_str, mcp_client):
    command_match = re.match(r'(read_query|list_tables|describe_table)\s*(.*)', command_str.strip())
    
    if not command_match:
        return "Invalid command. Use 'read_query', 'list_tables', or 'describe_table'."
    
    command, args = command_match.groups()
    try:
        tool_type = next((t for t in ToolType if t.value == command), None)
        
        if tool_type:
            params = ToolType.get_param_schema(tool_type, args.strip())
            result = await execute_tool(mcp_client, tool_type.value, params)
            return format_tool_result(result)
        else:
            return f"Unknown command: {command}"
    except Exception as e:
        return f"Error handling command: {e}"

# Streamlit app
def main():
    st.title("Jeopardy Database Query Tool")
    
    st.markdown("""
    ### Available Commands:
    - `list_tables` - List all tables in the database
    - `describe_table table_name` - Show schema for the specified table
    - `read_query SELECT * FROM table LIMIT 10;` - Execute SQL query
    """)
    
    # Command input
    command = st.text_area("Enter your command:", height=100)
    
    # Create placeholders for output and status
    output_placeholder = st.empty()
    status_placeholder = st.empty()
    
    if st.button("Execute"):
        if not command:
            st.error("Please enter a command.")
            return
            
        status_placeholder.info("Executing command...")
        
        # Run the command asynchronously
        try:
            async def execute_command():
                async with await setup_mcp_client() as mcp_client:
                    return await handle_command(command, mcp_client)
                    
            result = run_async(execute_command())
            status_placeholder.success("Command executed successfully!")
            output_placeholder.code(result)
            
        except Exception as e:
            status_placeholder.error(f"Error: {e}")
            
    # Additional settings section (collapsible)
    with st.expander("Settings"):
        st.text_input("Database Path", value="/Users/tomlegnard/repos/answer-there/jeopardy.db", 
                      help="Path to your SQLite database file")
        st.text_input("UV Path", value="/Users/tomlegnard/.local/bin/uv",
                     help="Path to your UV executable")
        st.text_input("MCP Server Directory", 
                     value="/Users/tomlegnard/repos/mcp/servers/src/sqlite",
                     help="Directory of the MCP server")

if __name__ == "__main__":
    main()