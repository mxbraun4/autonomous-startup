"""SQLite database for startup and VC data storage."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.utils.logging import get_logger
from src.utils.config import settings

logger = get_logger(__name__)


class StartupDatabase:
    """SQLite database for persistent startup and VC data storage."""

    def __init__(self, db_path: str = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path or settings.startup_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info(f"Database initialized at {self.db_path}")

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Startups table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS startups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sector TEXT,
                stage TEXT,
                description TEXT,
                founded INTEGER,
                location TEXT,
                team_size INTEGER,
                recent_news TEXT,
                fundraising_status TEXT,
                website TEXT,
                source TEXT,
                source_url TEXT,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # VCs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vcs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sectors TEXT,
                stage_focus TEXT,
                check_size TEXT,
                geography TEXT,
                portfolio_size INTEGER,
                recent_activity TEXT,
                website TEXT,
                source TEXT,
                source_url TEXT,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Outreach table - tracks all outreach attempts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_type TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                recipient_email TEXT,
                subject TEXT,
                message TEXT,
                channel TEXT DEFAULT 'email',
                status TEXT DEFAULT 'sent',
                response TEXT,
                response_at TIMESTAMP,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                campaign_id TEXT,
                metadata TEXT
            )
        """)

        self.conn.commit()

    def add_startup(self, startup: Dict[str, Any]) -> bool:
        """Add or update a startup in the database."""
        cursor = self.conn.cursor()
        try:
            startup_id = startup.get('id') or startup.get('name', '').lower().replace(' ', '_')
            cursor.execute("""
                INSERT OR REPLACE INTO startups
                (id, name, sector, stage, description, founded, location,
                 team_size, recent_news, fundraising_status, website, source, source_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                startup_id,
                startup.get('name'),
                startup.get('sector'),
                startup.get('stage'),
                startup.get('description'),
                startup.get('founded'),
                startup.get('location'),
                startup.get('team_size'),
                startup.get('recent_news'),
                startup.get('fundraising_status'),
                startup.get('website'),
                startup.get('source'),
                startup.get('source_url'),
                datetime.now()
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to add startup: {e}")
            return False

    def add_vc(self, vc: Dict[str, Any]) -> bool:
        """Add or update a VC in the database."""
        cursor = self.conn.cursor()
        try:
            vc_id = vc.get('id') or vc.get('name', '').lower().replace(' ', '_')
            sectors = json.dumps(vc.get('sectors', [])) if isinstance(vc.get('sectors'), list) else vc.get('sectors')
            geography = json.dumps(vc.get('geography', [])) if isinstance(vc.get('geography'), list) else vc.get('geography')

            cursor.execute("""
                INSERT OR REPLACE INTO vcs
                (id, name, sectors, stage_focus, check_size, geography,
                 portfolio_size, recent_activity, website, source, source_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vc_id,
                vc.get('name'),
                sectors,
                vc.get('stage_focus'),
                vc.get('check_size'),
                geography,
                vc.get('portfolio_size'),
                vc.get('recent_activity'),
                vc.get('website'),
                vc.get('source'),
                vc.get('source_url'),
                datetime.now()
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to add VC: {e}")
            return False

    def add_startups_batch(self, startups: List[Dict[str, Any]]) -> int:
        """Add multiple startups in batch."""
        count = sum(1 for s in startups if self.add_startup(s))
        return count

    def add_vcs_batch(self, vcs: List[Dict[str, Any]]) -> int:
        """Add multiple VCs in batch."""
        count = sum(1 for v in vcs if self.add_vc(v))
        return count

    def get_startups(
        self,
        sector: Optional[str] = None,
        stage: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get startups from database with optional filters."""
        cursor = self.conn.cursor()
        query = "SELECT * FROM startups WHERE 1=1"
        params = []

        if sector and sector != "all":
            query += " AND sector = ?"
            params.append(sector)

        if stage and stage != "all":
            query += " AND stage = ?"
            params.append(stage)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_vcs(
        self,
        sector: Optional[str] = None,
        stage_focus: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get VCs from database with optional filters."""
        cursor = self.conn.cursor()
        query = "SELECT * FROM vcs WHERE 1=1"
        params = []

        if sector and sector != "all":
            query += " AND sectors LIKE ?"
            params.append(f"%{sector}%")

        if stage_focus and stage_focus != "all":
            query += " AND stage_focus = ?"
            params.append(stage_focus)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        results = []
        for row in cursor.fetchall():
            vc = dict(row)
            for field in ['sectors', 'geography']:
                if vc.get(field):
                    try:
                        vc[field] = json.loads(vc[field])
                    except:
                        pass
            results.append(vc)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM startups")
        startup_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM vcs")
        vc_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM outreach")
        outreach_count = cursor.fetchone()[0]
        cursor.execute("SELECT DISTINCT sector FROM startups WHERE sector IS NOT NULL")
        sectors = [row[0] for row in cursor.fetchall()]
        return {
            'total_startups': startup_count,
            'total_vcs': vc_count,
            'total_outreach': outreach_count,
            'sectors': sectors
        }

    def log_outreach(
        self,
        recipient_type: str,
        recipient_id: str,
        recipient_name: str,
        subject: str,
        message: str,
        recipient_email: str = "",
        channel: str = "email",
        campaign_id: str = "",
        metadata: Dict[str, Any] = None
    ) -> int:
        """Log an outreach attempt.

        Args:
            recipient_type: Type of recipient (startup/vc)
            recipient_id: ID of the recipient
            recipient_name: Name of recipient
            subject: Email subject
            message: Email message body
            recipient_email: Email address
            channel: Outreach channel
            campaign_id: Campaign identifier
            metadata: Additional metadata

        Returns:
            ID of the outreach record
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO outreach
            (recipient_type, recipient_id, recipient_name, recipient_email,
             subject, message, channel, campaign_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            recipient_type,
            recipient_id,
            recipient_name,
            recipient_email,
            subject,
            message,
            channel,
            campaign_id,
            json.dumps(metadata) if metadata else None
        ))
        self.conn.commit()
        return cursor.lastrowid

    def get_outreach_history(
        self,
        recipient_id: str = None,
        campaign_id: str = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get outreach history.

        Args:
            recipient_id: Filter by recipient
            campaign_id: Filter by campaign
            limit: Maximum results

        Returns:
            List of outreach records
        """
        cursor = self.conn.cursor()
        query = "SELECT * FROM outreach WHERE 1=1"
        params = []

        if recipient_id:
            query += " AND recipient_id = ?"
            params.append(recipient_id)

        if campaign_id:
            query += " AND campaign_id = ?"
            params.append(campaign_id)

        query += " ORDER BY sent_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def update_outreach_response(
        self,
        outreach_id: int,
        response: str,
        status: str = "responded"
    ) -> bool:
        """Update outreach with response.

        Args:
            outreach_id: ID of outreach record
            response: Response received
            status: New status

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE outreach
            SET response = ?, status = ?, response_at = ?
            WHERE id = ?
        """, (response, status, datetime.now(), outreach_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def close(self):
        """Close database connection."""
        self.conn.close()
