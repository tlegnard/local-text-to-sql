# local-text-to-sql
A local, very basic, text-to-sql agent powered by Llama and MCP.

Some example prompts are given for working with a local SQLite database containing hsitorical Jeopardy! data.

# Setup

Note you may have to shallow clone the archived SQLite MCP server from [here](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/sqlite)

You'll also need to install `uv`, [setup an MCP server locally](https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector)  and have a SQLite database handy to connect the tool with.

I'm using the `ollama` cli installed via homebrew, this leverages Llama3.1

```
ollama pull llama3.1
# serve from dedicated terminal pane
ollama serve
```


# Run
```
streamlit run integrated_app.py
```
