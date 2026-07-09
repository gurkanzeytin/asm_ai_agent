from typing import Dict, Set, List
from app.database_intelligence.models import DatabaseSchema, TableMetadata

class SchemaNode:
    """Graph node representing a single table in the schema."""
    
    def __init__(self, table_metadata: TableMetadata):
        self.name = table_metadata.name
        self.metadata = table_metadata
        self.columns = [col.name for col in table_metadata.columns]
        self.primary_keys = set(table_metadata.primary_keys)
        self.foreign_keys = table_metadata.foreign_keys
        self.neighbors: Set[str] = set()


class SchemaGraph:
    """Graph representation of the inspected database schema where edges are FK relationships."""
    
    def __init__(self, schema: DatabaseSchema):
        self.nodes: Dict[str, SchemaNode] = {}
        self._build_graph(schema)

    def _build_graph(self, schema: DatabaseSchema) -> None:
        """Constructs graph nodes and undirected edges from foreign keys."""
        # 1. Initialize nodes
        for table_name, table in schema.tables.items():
            self.nodes[table_name] = SchemaNode(table)
            
        # 2. Establish undirected relationships based on FK references
        for table_name, node in self.nodes.items():
            for fk in node.foreign_keys:
                referred_table = fk.referred_table
                if referred_table in self.nodes:
                    node.neighbors.add(referred_table)
                    self.nodes[referred_table].neighbors.add(table_name)

    def get_neighbors(self, table_name: str) -> Set[str]:
        """Returns the set of neighbor table names for a given table."""
        node = self.nodes.get(table_name)
        return node.neighbors if node else set()
