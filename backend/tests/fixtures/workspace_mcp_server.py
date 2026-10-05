from mcp.server.fastmcp import FastMCP

mcp = FastMCP('Native verification fixture')


@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b


@mcp.resource('test://note')
def note() -> str:
    return 'Native resource'


if __name__ == '__main__':
    mcp.run()
