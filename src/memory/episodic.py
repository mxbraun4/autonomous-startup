"""Episodic memory - SQLite-backed storage for agent experiences."""
import sqlite3
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
from src.utils.logging import get_logger

logger = get_logger(__name__)


class EpisodicMemory:
    """SQLite-backed episodic memory for storing agent experiences."""

    def __init__(self, db_path: str = "data/memory/episodic.db"):
        """Initialize episodic memory.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        self._init_schema()
        logger.info(f"Initialized episodic memory at {db_path}")

    def _init_schema(self) -> None:
        """Create database schema if it doesn't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                episode_type TEXT NOT NULL,
                context TEXT NOT NULL,
                outcome TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                iteration INTEGER DEFAULT 0
            )
        """)

        # Create index for faster queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_type
            ON episodes(agent_id, episode_type)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_success
            ON episodes(success)
        """)

        self.conn.commit()

    def record(
        self,
        agent_id: str,
        episode_type: str,
        context: Dict[str, Any],
        outcome: Dict[str, Any],
        success: bool,
        iteration: int = 0
    ) -> int:
        """Record a new episode.

        Args:
            agent_id: ID of the agent
            episode_type: Type of episode (e.g., 'scraping', 'outreach_campaign')
            context: Context dict describing the situation
            outcome: Outcome dict describing results
            success: Whether the episode was successful
            iteration: Iteration number (for Build-Measure-Learn cycles)

        Returns:
            Episode ID
        """
        cursor = self.conn.execute("""
            INSERT INTO episodes (agent_id, episode_type, context, outcome, success, iteration)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            agent_id,
            episode_type,
            json.dumps(context),
            json.dumps(outcome),
            success,
            iteration
        ))

        self.conn.commit()
        episode_id = cursor.lastrowid

        logger.debug(
            f"Recorded episode {episode_id}: {agent_id}/{episode_type} "
            f"(success={success})"
        )

        return episode_id

    def search_similar(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[str] = None,
        context_keywords: Optional[List[str]] = None,
        success_only: bool = False,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for similar episodes.

        Args:
            agent_id: Filter by agent ID
            episode_type: Filter by episode type
            context_keywords: Keywords to search in context (simple substring matching)
            success_only: Only return successful episodes
            limit: Maximum number of results

        Returns:
            List of episode dicts
        """
        query = "SELECT * FROM episodes WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if episode_type:
            query += " AND episode_type = ?"
            params.append(episode_type)

        if success_only:
            query += " AND success = 1"

        # Simple keyword matching in context
        if context_keywords:
            for keyword in context_keywords:
                query += " AND context LIKE ?"
                params.append(f"%{keyword}%")

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()

        episodes = []
        for row in rows:
            episodes.append({
                'id': row['id'],
                'agent_id': row['agent_id'],
                'episode_type': row['episode_type'],
                'context': json.loads(row['context']),
                'outcome': json.loads(row['outcome']),
                'success': bool(row['success']),
                'timestamp': row['timestamp'],
                'iteration': row['iteration']
            })

        logger.debug(f"Retrieved {len(episodes)} episodes matching search criteria")
        return episodes

    def get_recent(self, agent_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent episodes.

        Args:
            agent_id: Optional agent ID filter
            limit: Maximum number of results

        Returns:
            List of recent episodes
        """
        return self.search_similar(agent_id=agent_id, limit=limit)

    def get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[str] = None
    ) -> float:
        """Calculate success rate for episodes.

        Args:
            agent_id: Optional agent ID filter
            episode_type: Optional episode type filter

        Returns:
            Success rate (0.0 to 1.0)
        """
        query = "SELECT AVG(CAST(success AS FLOAT)) as success_rate FROM episodes WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if episode_type:
            query += " AND episode_type = ?"
            params.append(episode_type)

        cursor = self.conn.execute(query, params)
        result = cursor.fetchone()

        return result['success_rate'] or 0.0

    def get_learning_insights(
        self,
        episode_type: str,
        iteration: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get learning insights for an episode type.

        Args:
            episode_type: Type of episode
            iteration: Optional specific iteration

        Returns:
            Dict with insights
        """
        episodes = self.search_similar(
            episode_type=episode_type,
            success_only=True,
            limit=50
        )

        if iteration is not None:
            episodes = [e for e in episodes if e['iteration'] == iteration]

        if not episodes:
            return {'total': 0, 'success_rate': 0.0, 'insights': []}

        # Aggregate insights
        total = len(episodes)
        success_count = sum(1 for e in episodes if e['success'])
        success_rate = success_count / total if total > 0 else 0.0

        # Extract common patterns from successful episodes
        insights = []
        for episode in episodes[:5]:  # Top 5 recent successful episodes
            insights.append({
                'context': episode['context'],
                'outcome': episode['outcome'],
                'timestamp': episode['timestamp']
            })

        return {
            'total': total,
            'success_rate': success_rate,
            'insights': insights
        }

    def clear(self) -> None:
        """Clear all episodes from memory."""
        self.conn.execute("DELETE FROM episodes")
        self.conn.commit()
        logger.info("Cleared episodic memory")

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
