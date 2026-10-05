"""One owner for how the backend reaches the law graph (Neo4j).

NEO4J_URI is the same name ops/compose.yml hands the law containers. Code that
treats "unset" as "graph disabled" asks neo4j_configured(); code that always
connects takes neo4j_uri() and gets the local default.
"""
import os

DEFAULT_URI = 'bolt://127.0.0.1:7687'


def neo4j_configured(env=os.environ):
    return bool(str(env.get('NEO4J_URI') or '').strip())


def neo4j_uri(env=os.environ):
    return str(env.get('NEO4J_URI') or '').strip() or DEFAULT_URI


def neo4j_credentials(env=os.environ):
    # No password default: a wrong guess fails the same way, less quietly.
    return str(env.get('NEO4J_USER') or 'neo4j'), str(env.get('NEO4J_PASSWORD') or '')


def neo4j_database(env=os.environ):
    return str(env.get('NEO4J_DATABASE') or 'neo4j')
