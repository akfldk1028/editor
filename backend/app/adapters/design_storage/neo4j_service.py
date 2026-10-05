"""
Neo4j Database Service
Provides Neo4j connection and operations for the agent system
"""

import os
import logging
from typing import Optional, Dict, Any, List
from neo4j import GraphDatabase, Driver, Session
from django.conf import settings

logger = logging.getLogger(__name__)

class Neo4jService:
    """Neo4j database connection and operations manager"""

    def __init__(self, uri: str = None, user: str = None, password: str = None, database: str = None):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://172.27.80.1:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "11111111")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")  # Use neo4j as default database

        self._driver: Optional[Driver] = None
        self._session: Optional[Session] = None

    def connect(self) -> bool:
        """Establish connection to Neo4j database"""
        try:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )

            # Test connection
            with self._driver.session() as session:
                result = session.run("RETURN 1 as test")
                test_value = result.single()["test"]

            if test_value == 1:
                logger.info(f"Successfully connected to Neo4j at {self.uri}")
                return True
            else:
                logger.error("Failed to verify Neo4j connection")
                return False

        except Exception as e:
            logger.error(f"Error connecting to Neo4j: {str(e)}")
            return False

    def disconnect(self):
        """Close the database connection"""
        if self._session:
            self._session.close()
            self._session = None

        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Disconnected from Neo4j")

    @property
    def driver(self) -> Driver:
        """Get the driver instance (read-only property)"""
        if not self._driver:
            raise RuntimeError("Not connected to database. Call connect() first.")
        return self._driver

    def get_session(self) -> Session:
        """Get a new database session"""
        if not self._driver:
            raise RuntimeError("Not connected to database. Call connect() first.")
        return self._driver.session(database=self.database)

    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict]:
        """Execute a Cypher query and return results"""
        try:
            # Ensure string parameters are properly encoded
            if parameters:
                encoded_params = {}
                for key, value in parameters.items():
                    if isinstance(value, str):
                        # Ensure UTF-8 encoding for string parameters
                        encoded_params[key] = value.encode('utf-8').decode('utf-8')
                    elif isinstance(value, list):
                        # Handle list of strings
                        encoded_params[key] = [
                            v.encode('utf-8').decode('utf-8') if isinstance(v, str) else v
                            for v in value
                        ]
                    else:
                        encoded_params[key] = value
                parameters = encoded_params

            with self.get_session() as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    def execute_write_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict]:
        """Execute a write query (CREATE, UPDATE, DELETE)"""
        try:
            with self.get_session() as session:
                def _execute_transaction(tx):
                    result = tx.run(query, parameters or {})
                    return [record.data() for record in result]

                return session.write_transaction(_execute_transaction)
        except Exception as e:
            logger.error(f"Error executing write query: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    async def execute_async_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict]:
        """Execute query asynchronously (wrapper for sync method)"""
        # Note: Neo4j Python driver doesn't have true async support yet
        # This is a wrapper for compatibility with async code
        return self.execute_query(query, parameters)

    async def execute_async_write_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict]:
        """Execute write query asynchronously (wrapper for sync method)"""
        return self.execute_write_query(query, parameters)

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


# Global service instance
_neo4j_service: Optional[Neo4jService] = None

def get_neo4j_service() -> Neo4jService:
    """Get or create Neo4j service instance"""
    global _neo4j_service
    if _neo4j_service is None:
        _neo4j_service = Neo4jService()
        _neo4j_service.connect()
    return _neo4j_service

def initialize_neo4j() -> bool:
    """Initialize Neo4j connection"""
    service = get_neo4j_service()
    if service._driver:
        # Create indexes
        from .indexes import create_all_indexes
        create_all_indexes(service)

        # Get stats
        from .stats import get_database_stats
        stats = get_database_stats(service)
        logger.info(f"📊 Neo4j Database stats: {stats}")
        return True
    return False

def shutdown_neo4j():
    """Gracefully shutdown Neo4j connection"""
    global _neo4j_service
    if _neo4j_service:
        _neo4j_service.disconnect()
        _neo4j_service = None
