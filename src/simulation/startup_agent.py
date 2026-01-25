"""Simulated Startup Agent - Responds to outreach."""
import random
from typing import Dict, Any
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimulatedStartup:
    """Simulated startup that responds to outreach."""

    def __init__(self, startup_profile: Dict[str, Any]):
        """Initialize simulated startup.

        Args:
            startup_profile: Startup profile dict
        """
        self.profile = startup_profile
        self.agent_id = f"startup_{startup_profile.get('id', 'unknown')}"

    def receive_outreach(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate startup's response to outreach.

        Args:
            message: Outreach message dict

        Returns:
            Response dict
        """
        message_text = message.get('message', '')

        # Calculate response probability based on message quality
        personalization_score = message.get('personalization_score', 0.5)
        matched_vcs = message.get('matched_vcs', [])

        # Base response probability
        response_prob = 0.15  # 15% base rate

        # Increase if personalized
        if personalization_score > 0.5:
            response_prob += 0.15

        # Increase if VCs are well-matched
        if matched_vcs:
            well_matched = sum(1 for vc in matched_vcs if vc.get('sector_match'))
            response_prob += 0.1 * well_matched

        # Increase if fundraising is active
        if self.profile.get('fundraising_status') == 'active':
            response_prob += 0.10

        # Determine response
        will_respond = random.random() < response_prob

        if will_respond:
            # Determine level of interest
            interest_score = (personalization_score + response_prob) / 2

            if interest_score > 0.6:
                return {
                    'response': 'interested',
                    'message': (
                        f"Thanks for reaching out! We're actively raising our "
                        f"{self.profile.get('stage', 'seed')} round for {self.profile.get('name')}. "
                        f"I'd love to learn more about the VCs you mentioned. "
                        f"Can we schedule a brief call?"
                    ),
                    'wants_meeting': True,
                    'interest_level': 'high'
                }
            elif interest_score > 0.4:
                return {
                    'response': 'interested',
                    'message': (
                        f"Hi, thanks for the note. We're interested in connecting with VCs "
                        f"in the {self.profile.get('sector', 'tech')} space. "
                        f"Can you share more details?"
                    ),
                    'wants_meeting': False,
                    'interest_level': 'medium'
                }
            else:
                return {
                    'response': 'interested',
                    'message': "Thanks for reaching out. Please send more information.",
                    'wants_meeting': False,
                    'interest_level': 'low'
                }
        else:
            # No response or polite decline
            if random.random() < 0.3:  # 30% of non-responders send polite decline
                return {
                    'response': 'not_interested',
                    'message': "Thanks, but we're not fundraising at this time.",
                    'wants_meeting': False,
                    'interest_level': 'none'
                }
            else:
                return {
                    'response': 'no_response',
                    'message': None,
                    'wants_meeting': False,
                    'interest_level': 'none'
                }

    def __str__(self) -> str:
        """String representation.

        Returns:
            String representation
        """
        return (
            f"Startup: {self.profile.get('name')} "
            f"({self.profile.get('sector')}, {self.profile.get('stage')})"
        )
