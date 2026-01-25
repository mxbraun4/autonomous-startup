"""Simulated VC Agent - Evaluates startups."""
from typing import Dict, Any
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimulatedVC:
    """Simulated VC that evaluates startups."""

    def __init__(self, vc_profile: Dict[str, Any]):
        """Initialize simulated VC.

        Args:
            vc_profile: VC profile dict
        """
        self.profile = vc_profile
        self.agent_id = f"vc_{vc_profile.get('id', 'unknown')}"

    def evaluate_startup(self, startup_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate VC's evaluation of a startup.

        Args:
            startup_profile: Startup profile dict

        Returns:
            Evaluation dict
        """
        alignment_score = self._calculate_alignment(startup_profile)

        # Determine decision based on alignment
        if alignment_score > 0.7:
            decision = 'meeting_request'
            message = (
                f"We're very interested in {startup_profile.get('name')}. "
                f"Our portfolio has strong synergies in the {startup_profile.get('sector')} space. "
                f"Let's schedule a partner meeting."
            )
        elif alignment_score > 0.5:
            decision = 'interested'
            message = (
                f"Interesting company. We'd like to learn more about your traction "
                f"and growth plans. Can you share your deck?"
            )
        elif alignment_score > 0.3:
            decision = 'maybe'
            message = (
                f"Thanks for sharing. We're monitoring the {startup_profile.get('sector')} "
                f"space. Please keep us updated on your progress."
            )
        else:
            decision = 'pass'
            message = (
                f"Thanks for reaching out. This isn't a fit for our current thesis, "
                f"but we wish you success."
            )

        return {
            'decision': decision,
            'alignment_score': alignment_score,
            'message': message,
            'vc_name': self.profile.get('name')
        }

    def _calculate_alignment(self, startup: Dict[str, Any]) -> float:
        """Calculate alignment score between VC and startup.

        Args:
            startup: Startup profile dict

        Returns:
            Alignment score (0-1)
        """
        score = 0.0

        # Sector alignment (most important)
        startup_sector = startup.get('sector', 'unknown')
        vc_sectors = self.profile.get('sectors', [])

        if startup_sector in vc_sectors:
            score += 0.5  # Perfect sector match
        else:
            # Check for related sectors
            related_sectors = {
                'fintech': ['ai_ml', 'devtools'],
                'healthtech': ['ai_ml', 'biotech'],
                'ai_ml': ['devtools', 'fintech', 'healthtech']
            }

            if startup_sector in related_sectors:
                for related in related_sectors[startup_sector]:
                    if related in vc_sectors:
                        score += 0.2  # Partial sector match
                        break

        # Stage alignment
        startup_stage = startup.get('stage', 'unknown')
        vc_stage = self.profile.get('stage_focus', 'unknown')

        if startup_stage == vc_stage:
            score += 0.3
        else:
            # Adjacent stages are somewhat compatible
            stage_map = {
                'seed': ['series_a'],
                'series_a': ['seed', 'series_b'],
                'series_b': ['series_a', 'series_c']
            }

            if startup_stage in stage_map and vc_stage in stage_map.get(startup_stage, []):
                score += 0.15

        # Geography alignment (less important)
        startup_location = startup.get('location', '')
        vc_geographies = self.profile.get('geography', [])

        # Simple matching on country/region
        for geo in vc_geographies:
            if any(g.lower() in startup_location.lower() for g in geo.split()):
                score += 0.1
                break

        # Fundraising status (if actively fundraising, boost score slightly)
        if startup.get('fundraising_status') == 'active':
            score += 0.1

        # Cap at 1.0
        return min(score, 1.0)

    def __str__(self) -> str:
        """String representation.

        Returns:
            String representation
        """
        sectors = ', '.join(self.profile.get('sectors', []))
        return (
            f"VC: {self.profile.get('name')} "
            f"({sectors}, {self.profile.get('stage_focus')})"
        )
