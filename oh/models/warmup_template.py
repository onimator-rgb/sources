"""
Domain models for the Warmup Templates feature.

Pure dataclasses — no I/O, no logic.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class WarmupTemplate:
    """One row in the warmup_templates table."""
    name: str
    follow_start: int = 10
    follow_increment: int = 5
    follow_cap: int = 50
    like_start: int = 20
    like_increment: int = 5
    like_cap: int = 80
    auto_increment: bool = True
    enable_follow: bool = True
    enable_like: bool = True
    is_default: bool = False
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    id: Optional[int] = None

    def to_bot_settings(self) -> Dict[str, object]:
        """Convert template fields to settings.db key-value pairs.

        Returns the correct Python type per key:
          - int for limit-perday keys
          - str for auto-increment amount/cap keys (bot stores as strings)
          - bool for toggle keys
        """
        return {
            "default_action_limit_perday": self.follow_start,
            "like_limit_perday": self.like_start,
            "enable_auto_increment_follow_limit_perday": self.auto_increment,
            "enable_auto_increment_like_limit_perday": self.auto_increment,
            "auto_increment_action_limit_by": str(self.follow_increment),
            "max_increment_action_limit": str(self.follow_cap),
            "auto_increment_like_limit_perday_increase": str(self.like_increment),
            "auto_increment_like_limit_perday_increase_limit": str(self.like_cap),
            "enable_follow_joborders": self.enable_follow,
            "enable_likepost": self.enable_like,
        }

    def to_preview_lines(self) -> List[str]:
        """Human-readable summary lines for confirmation dialogs."""
        lines = [
            f"Follow: start {self.follow_start}/day, +{self.follow_increment}/day, cap {self.follow_cap}",
            f"Like: start {self.like_start}/day, +{self.like_increment}/day, cap {self.like_cap}",
            f"Auto-increment: {'ON' if self.auto_increment else 'OFF'}",
        ]
        if not self.enable_follow:
            lines.append("Follow action: DISABLED")
        if not self.enable_like:
            lines.append("Like action: DISABLED")
        return lines


@dataclass
class WarmupDeployPreview:
    """Preview of what warmup deploy will change for one account."""
    account_id: int
    username: str
    device_name: Optional[str]
    current_values: dict
    new_values: dict
    changes: List[str]
    error: Optional[str] = None


@dataclass
class WarmupDeployResult:
    """Result of deploying warmup template to one account."""
    account_id: int
    username: str
    device_name: Optional[str]
    success: bool
    backed_up: bool
    keys_written: List[str]
    error: Optional[str] = None


@dataclass
class WarmupDeployBatchResult:
    """Aggregate result for the entire warmup deploy operation."""
    template_name: str
    total_targets: int
    success_count: int
    fail_count: int
    results: List[WarmupDeployResult]
