"""
Domain models for the Settings Copier feature.

Pure dataclasses — no I/O, no logic.
COPYABLE_SETTINGS is the legacy allowlist (kept for backward compatibility).
SETTINGS_CATEGORIES is the expanded categorised structure with all 9 categories.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set


# ---------------------------------------------------------------------------
# Legacy flat allowlist — kept for backward compatibility
# ---------------------------------------------------------------------------

COPYABLE_SETTINGS = {
    "default_action_limit_perday": "Follow limit / day",
    "like_limit_perday": "Like limit / day",
    "unfollow_limit_perday": "Unfollow limit / day",
    "start_time": "Working hours — start",
    "end_time": "Working hours — end",
    "follow_enabled": "Follow enabled",
    "unfollow_enabled": "Unfollow enabled",
    "like_enabled": "Like enabled",
    "dm_enabled": "DM enabled",
    "dm_limit_perday": "DM limit / day",
    "enable_auto_increment_follow_limit_perday": "Auto-increment follow enabled",
    "enable_auto_increment_like_limit_perday": "Auto-increment like enabled",
    "auto_increment_action_limit_by": "Follow daily increase",
    "auto_increment_like_limit_perday_increase": "Like daily increase",
    "auto_increment_like_limit_perday_increase_limit": "Like auto-increment cap",
    "max_increment_action_limit": "Follow auto-increment cap",
    "enable_follow_joborders": "Follow action enabled",
    "enable_likepost": "Like action enabled",
}


# ---------------------------------------------------------------------------
# Expanded categorised settings model
# ---------------------------------------------------------------------------

@dataclass
class SettingDef:
    """One copyable setting: JSON key path + display name."""
    key: str            # JSON path — dot notation for nested (e.g. "follow_method.follow_followers")
    display_name: str


@dataclass
class SettingsCategory:
    """A named group of related settings."""
    name: str                   # e.g. "Follow"
    key: str                    # e.g. "follow"
    settings: List[SettingDef]


# All 9 categories with EXACT key paths from Helper Suite OnimatorSettingsCopier.
SETTINGS_CATEGORIES: List[SettingsCategory] = [
    # ----- 1. Follow -----
    SettingsCategory(
        name="Follow",
        key="follow",
        settings=[
            # Follow Method
            SettingDef("follow_method.follow_followers", "Follow User's Followers"),
            SettingDef("follow_method.follow_likers", "Follow User's Likers"),
            SettingDef("follow_method.follow_specific_user", "Follow Specific Users"),
            SettingDef("follow_method.follow_using_word_search", "Follow Accounts Using Keyword Search"),
            SettingDef("follow_method.follow_followers_own_followers", "Follow Followers of Own Followers"),
            # Follow Tool Toggles
            SettingDef("follow_enabled", "Follow Enabled"),
            SettingDef("enable_follow_joborders", "Follow Action Enabled"),
            # Follow Action
            SettingDef("min_user_follow", "Follows per Operation (Min)"),
            SettingDef("max_user_follow", "Follows per Operation (Max)"),
            SettingDef("follow_min_delay", "Delay after Following (Min Seconds)"),
            SettingDef("follow_max_delay", "Delay after Following (Max Seconds)"),
            SettingDef("followings_limit", "Total Followings Limit"),
            SettingDef("default_action_limit_perday", "Follow Limit per Day"),
            # Auto-increment
            SettingDef("enable_auto_increment_follow_limit_perday", "Auto-increment Follow Enabled"),
            SettingDef("auto_increment_action_limit_by", "Follow Daily Increase"),
            SettingDef("max_increment_action_limit", "Follow Auto-increment Cap"),
            # Working Hours
            SettingDef("start_time", "Working Hours — Start"),
            SettingDef("end_time", "Working Hours — End"),
            # Follow User's Followers Additional
            SettingDef("visit_profile_when_following_using_followfollowers", "Visit Target Profile when Following"),
            SettingDef("scroll_profile_when_following_using_followfollowers", "Scroll Profile When Visiting"),
            SettingDef("enable_random_like_when_following_using_followers", "Like Random Posts When Visiting"),
            # Follow User's Likers Additional
            SettingDef("visit_profile_when_following_using_followlikers", "Visit Target Profile when Following Likers"),
            # Follow Specific Users Additional
            SettingDef("scroll_profile_when_following_using_followspecificuser", "Scroll Profile When Visiting (Specific Users)"),
            SettingDef("enable_random_like_when_following_using_followspecificuser", "Like Random Posts When Visiting (Specific Users)"),
            # Follow Followers of Own Followers Additional
            SettingDef("visit_profile_when_follow_followers_own_followers", "Visit Profile (Own Followers)"),
            SettingDef("scroll_profile_when_follow_followers_own_followers", "Scroll Profile (Own Followers)"),
            SettingDef("enable_random_like_when_follow_followers_own_followers", "Like Random Posts (Own Followers)"),
            # Follow Using Keyword Search Additional
            SettingDef("enable_random_like_post_after_follow_using_word_search", "Randomly Like Post after Follow"),
            SettingDef("enable_random_comment_post_after_follow_using_word_search", "Randomly Comment Post using AI"),
            # Additional Settings
            SettingDef("mute_after_follow", "Mute Users after Follow"),
            SettingDef("enable_name_must_include", "Follow only if Account's Name includes"),
            SettingDef("enable_name_must_not_include", "Do not Follow if Account's Name includes"),
            SettingDef("enable_complete_follow_first_before_unfollowing", "Complete Follow daily limit first before Unfollowing"),
            SettingDef("enable_dont_follow_sametag_accounts", "Don't Follow user that was already followed"),
            SettingDef("enable_dont_follow_if_post_like", "Don't Follow user that was already liked using like action"),
            SettingDef("enable_follow_only_if_story_exist", "Only Follow user that has active stories"),
            SettingDef("like_story_after_follow", "Like Stories after Following"),
            SettingDef("story_like_peraccount", "Stories to Like per Account"),
            # Filters
            SettingDef("enable_filters", "Enable Filters"),
            SettingDef("filters.enable_posts_filter", "Enable Posts Count Filter"),
            SettingDef("filters.min_posts", "Posts Min"),
            SettingDef("filters.max_posts", "Posts Max"),
            SettingDef("filters.enable_followers_filter", "Enable Followers Count Filter"),
            SettingDef("filters.min_followers", "Followers Min"),
            SettingDef("filters.max_followers", "Followers Max"),
            SettingDef("filters.enable_followings_filter", "Enable Followings Count Filter"),
            SettingDef("filters.min_followings", "Followings Min"),
            SettingDef("filters.max_followings", "Followings Max"),
            SettingDef("filters.enable_verified_account_filter", "Enable Verified Account Filter"),
            SettingDef("filters.should_be_verified_account", "Follow only Verified Accounts"),
            SettingDef("filters.enable_business_account_filter", "Enable Business Account Filter"),
            SettingDef("filters.should_be_business_account", "Follow only Business Accounts"),
            SettingDef("filters.only_public_accounts", "Do not Follow Private Accounts"),
            # Schedule Settings
            SettingDef("enable_follow_is_weekdays", "Enable Days of the Week to Follow"),
            SettingDef("follow_is_weekdays.Monday", "Follow Monday"),
            SettingDef("follow_is_weekdays.Tuesday", "Follow Tuesday"),
            SettingDef("follow_is_weekdays.Wednesday", "Follow Wednesday"),
            SettingDef("follow_is_weekdays.Thursday", "Follow Thursday"),
            SettingDef("follow_is_weekdays.Friday", "Follow Friday"),
            SettingDef("follow_is_weekdays.Saturday", "Follow Saturday"),
            SettingDef("follow_is_weekdays.Sunday", "Follow Sunday"),
            SettingDef("enable_specific_follow_limit_perday", "Enable Specific Limit per Day to Follow"),
            SettingDef("specific_follow_limit_perday.Monday", "Follow Monday Limit"),
            SettingDef("specific_follow_limit_perday.Tuesday", "Follow Tuesday Limit"),
            SettingDef("specific_follow_limit_perday.Wednesday", "Follow Wednesday Limit"),
            SettingDef("specific_follow_limit_perday.Thursday", "Follow Thursday Limit"),
            SettingDef("specific_follow_limit_perday.Friday", "Follow Friday Limit"),
            SettingDef("specific_follow_limit_perday.Saturday", "Follow Saturday Limit"),
            SettingDef("specific_follow_limit_perday.Sunday", "Follow Sunday Limit"),
        ],
    ),

    # ----- 2. Unfollow -----
    SettingsCategory(
        name="Unfollow",
        key="unfollow",
        settings=[
            # Unfollow Method
            SettingDef("unfollow_method.unfollow_using_search", "Unfollow Using IG Search"),
            SettingDef("unfollow_method.unfollow_using_profile", "Unfollow Using Own Following Page Via Search"),
            SettingDef("unfollow_method.unfollow_using_profile_scroll", "Unfollow Using Own Following Page Via Scrolling"),
            # Unfollow Action
            SettingDef("min_user_unfollow", "Unfollows per Operation (Min)"),
            SettingDef("max_user_unfollow", "Unfollows per Operation (Max)"),
            SettingDef("unfollow_min_delay", "Delay after Unfollowing (Min Seconds)"),
            SettingDef("unfollow_max_delay", "Delay after Unfollowing (Max Seconds)"),
            SettingDef("unfollowdelayday", "Days before Unfollowing"),
            SettingDef("default_unfollow_limit_perday", "Unfollow Limit per Day"),
            # Unfollow Tool Toggle
            SettingDef("unfollow_enabled", "Unfollow Enabled"),
            SettingDef("unfollow_limit_perday", "Unfollow Limit per Day (legacy)"),
            # Additional Settings
            SettingDef("enable_follow_if_no_users_to_unfollow", "Enable Follow Tool if no users to Unfollow"),
            SettingDef("dont_unfollow_followers", "Don't Unfollow Followers"),
            SettingDef("enable_close_friend", "Don't Unfollow Close Friends"),
            SettingDef("enable_unfollow_specific_accounts", "Unfollow Specific Accounts"),
            # Schedule Settings
            SettingDef("enable_unfollow_is_weekdays", "Enable Days of the Week to Unfollow"),
            SettingDef("unfollow_is_weekdays.Monday", "Unfollow Monday"),
            SettingDef("unfollow_is_weekdays.Tuesday", "Unfollow Tuesday"),
            SettingDef("unfollow_is_weekdays.Wednesday", "Unfollow Wednesday"),
            SettingDef("unfollow_is_weekdays.Thursday", "Unfollow Thursday"),
            SettingDef("unfollow_is_weekdays.Friday", "Unfollow Friday"),
            SettingDef("unfollow_is_weekdays.Saturday", "Unfollow Saturday"),
            SettingDef("unfollow_is_weekdays.Sunday", "Unfollow Sunday"),
            SettingDef("enable_specific_unfollow_limit_perday", "Enable Specific Limit per Day to Unfollow"),
            SettingDef("specific_unfollow_limit_perday.Monday", "Unfollow Monday Limit"),
            SettingDef("specific_unfollow_limit_perday.Tuesday", "Unfollow Tuesday Limit"),
            SettingDef("specific_unfollow_limit_perday.Wednesday", "Unfollow Wednesday Limit"),
            SettingDef("specific_unfollow_limit_perday.Thursday", "Unfollow Thursday Limit"),
            SettingDef("specific_unfollow_limit_perday.Friday", "Unfollow Friday Limit"),
            SettingDef("specific_unfollow_limit_perday.Saturday", "Unfollow Saturday Limit"),
            SettingDef("specific_unfollow_limit_perday.Sunday", "Unfollow Sunday Limit"),
        ],
    ),

    # ----- 3. Like -----
    SettingsCategory(
        name="Like",
        key="like",
        settings=[
            # Like Method
            SettingDef("likepost_method.enable_likepost_sources_followers", "Like Source's Followers"),
            SettingDef("likepost_method.enable_likepost_via_keywords", "Like Likers of Posts Via Keywords Search"),
            SettingDef("likepost_method.enable_likepost_specific_accounts", "Like Posts of Specific Accounts"),
            # Like Action
            SettingDef("min_likepost_action", "Likes per Operation (Min)"),
            SettingDef("max_likepost_action", "Likes per Operation (Max)"),
            SettingDef("like_min_delay", "Delay after Liking (Min Seconds)"),
            SettingDef("like_max_delay", "Delay after Liking (Max Seconds)"),
            SettingDef("like_limit_perday", "Like Limit per Day"),
            # Like Tool Toggles
            SettingDef("like_enabled", "Like Enabled"),
            SettingDef("enable_likepost", "Like Action Enabled"),
            # Auto-increment
            SettingDef("enable_auto_increment_like_limit_perday", "Auto-increment Like Enabled"),
            SettingDef("auto_increment_like_limit_perday_increase", "Like Daily Increase"),
            SettingDef("auto_increment_like_limit_perday_increase_limit", "Like Auto-increment Cap"),
            # Additional Settings
            SettingDef("enable_filter_seach_followers_like", "Filter Word Search In Followers Tab"),
            SettingDef("name_must_include_likes", "Like only if Account's Name includes"),
            SettingDef("name_must_not_include_likes", "Do not Like if Account's Name includes"),
            SettingDef("enable_scrape_before_likingpost", "Scrape Accounts before Liking posts"),
            SettingDef("enable_dont_like_sametag_accounts", "Don't Like user that was already Liked"),
            SettingDef("enable_dont_like_if_user_followed", "Don't Like user if it was already followed"),
            SettingDef("like_story_after_liking_post", "Like Stories after Liking Posts"),
            SettingDef("story_like_peraccount_like_post", "Stories to Like per Account (Like)"),
            SettingDef("min_post_to_like", "Posts to Like per User (Min)"),
            SettingDef("max_post_to_like", "Posts to Like per User (Max)"),
            # Like Filters
            SettingDef("like_enable_filters", "Enable Like Filters"),
            SettingDef("filters_like.enable_posts_filter", "Like Enable Posts Count"),
            SettingDef("filters_like.min_posts", "Like Posts Min"),
            SettingDef("filters_like.max_posts", "Like Posts Max"),
            SettingDef("filters_like.enable_followers_filter", "Like Enable Followers Count"),
            SettingDef("filters_like.min_followers", "Like Followers Min"),
            SettingDef("filters_like.max_followers", "Like Followers Max"),
            SettingDef("filters_like.enable_followings_filter", "Like Enable Followings Count"),
            SettingDef("filters_like.min_followings", "Like Followings Min"),
            SettingDef("filters_like.max_followings", "Like Followings Max"),
            SettingDef("filters_like.enable_verified_account_filter", "Like Enable Verified Account Filter"),
            SettingDef("filters_like.should_be_verified_account", "Like Only Verified Accounts"),
            SettingDef("filters_like.enable_business_account_filter", "Like Enable Business Account Filter"),
            SettingDef("filters_like.should_be_business_account", "Like Only Business Accounts"),
            SettingDef("filters_like.only_public_accounts", "Do not Like Private Accounts"),
        ],
    ),

    # ----- 4. Story -----
    SettingsCategory(
        name="Story",
        key="story",
        settings=[
            # Story Method
            SettingDef("view_method.view_followers", "View Stories of User's Followers"),
            SettingDef("view_method.view_likers", "View Stories of User's Likers"),
            SettingDef("view_method.view_specific_user", "View Stories of Specific Users"),
            SettingDef("view_method.view_specific_user_highlight", "View Stories of Specific Users Highlights"),
            SettingDef("view_method.view_storyplus", "View Story Plus"),
            # Story Action
            SettingDef("story_viewer_min", "Story Views per Operation (Min)"),
            SettingDef("story_viewer_max", "Story Views per Operation (Max)"),
            SettingDef("story_view_peraccount_view", "Stories to View per Account"),
            SettingDef("story_viewer_daily_limit", "Story Viewer Limit per Day"),
            # Additional Settings
            SettingDef("visit_profile_when_viewing_story_via_viewfollowers", "Visit Target Profile when Viewing Stories"),
            SettingDef("view_story_directly_in_searchbox", "View Specific user's story directly in search box"),
            SettingDef("view_story_directly_in_searchbox_storyplus", "View Specific user's story directly in search box (Story Plus)"),
            SettingDef("like_story_after_viewing", "Like Stories after Viewing"),
            SettingDef("dont_view_same_account_twice", "Don't View the same Account twice"),
            SettingDef("view_highlight_if_no_story_viceversa", "View Highlights if no Story and Viceversa"),
            SettingDef("min_story_like_peraccount_view", "Story Likes per Account (Min)"),
            SettingDef("max_story_like_peraccount_view", "Story Likes per Account (Max)"),
            SettingDef("story_like_daily_limit", "Story Like Daily Limit"),
        ],
    ),

    # ----- 5. Reels -----
    SettingsCategory(
        name="Reels",
        key="reels",
        settings=[
            SettingDef("enable_watch_reels", "Enable Reels Watching"),
            SettingDef("min_reels_to_watch", "Reels per Operation (Min)"),
            SettingDef("max_reels_to_watch", "Reels per Operation (Max)"),
            SettingDef("min_sec_reel_watch", "Seconds per Reel (Min)"),
            SettingDef("max_sec_reel_watch", "Seconds per Reel (Max)"),
            SettingDef("enable_like_reel", "Enable Like Reel while watching"),
            SettingDef("like_reel_percent", "Chance to Like Reel (Percentage)"),
            SettingDef("enable_save_reels_after_watching", "Save Reels after watching"),
        ],
    ),

    # ----- 6. DM -----
    SettingsCategory(
        name="DM",
        key="dm",
        settings=[
            SettingDef("dm_enabled", "DM Enabled"),
            SettingDef("dm_limit_perday", "DM Limit per Day (legacy)"),
            SettingDef("enable_directmessage", "Enable Direct Message"),
            # DM Method
            SettingDef("directmessage_method.directmessage_new_followers", "Message New Followers"),
            SettingDef("directmessage_method.directmessage_specificuser", "Message Specific Users"),
            SettingDef("directmessage_method.directmessage_reply", "Reply to Messages"),
            # DM Action
            SettingDef("directmessage_min", "Messages per Operation (Min)"),
            SettingDef("directmessage_max", "Messages per Operation (Max)"),
            SettingDef("directmessage_min_delay", "Delay after Messaging (Min Seconds)"),
            SettingDef("directmessage_max_delay", "Delay after Messaging (Max Seconds)"),
            SettingDef("directmessage_daily_limit", "Message Daily Limit"),
            SettingDef("message_check_delay", "Message Check Delay (Minutes)"),
            # Additional DM Settings
            SettingDef("enable_auto_increment_directmessage_daily_limit", "Auto Increment DM Limit per Day"),
            SettingDef("auto_increment_directmessage_daily_limit_increase", "DM Added Daily Limit"),
            SettingDef("auto_increment_directmessage_daily_limit_increase_limit", "DM Auto-increment Cap"),
            SettingDef("enable_send_message_every_new_line", "Enable Send Message Every New Line"),
            SettingDef("enable_dm_requests", "Enable DM Requests"),
            SettingDef("enable_openai_assistant", "Enable Open AI Assistant"),
        ],
    ),

    # ----- 7. Share -----
    SettingsCategory(
        name="Share",
        key="share",
        settings=[
            SettingDef("enable_shared_post", "Enable Shared Post"),
            # Share Source
            SettingDef("enable_share_post_to_story", "Share Post or Reels To Story"),
            SettingDef("enable_repost_post", "Repost Post or Reels"),
            # Share Action
            SettingDef("post_type_to_share", "Post Type to Share"),
            # Watch Time
            SettingDef("min_sec_share_reel_watch", "Watch Time Per Reel (Min Seconds)"),
            SettingDef("max_sec_share_reel_watch", "Watch Time Per Reel (Max Seconds)"),
            # Link Settings
            SettingDef("enable_add_link_to_story", "Enable Add Link to Story"),
            SettingDef("link_to_story", "Link to Story"),
            SettingDef("custom_link_text", "Custom Link Text"),
            # Mention Settings
            SettingDef("enable_mention_to_story", "Enable Mention to Story"),
            SettingDef("sharepost_mention", "Mention Username"),
            # Share Limits
            SettingDef("shared_post_limit_persource_perday", "Share Limit per Source per Day"),
            SettingDef("shared_post_limit_perday", "Share Limit per Day"),
        ],
    ),

    # ----- 8. Post -----
    SettingsCategory(
        name="Post",
        key="post",
        settings=[
            SettingDef("enable_scheduled_post", "Enable Scheduled Post"),
        ],
    ),

    # ----- 9. Human Behavior -----
    SettingsCategory(
        name="Human Behavior",
        key="human_behavior",
        settings=[
            SettingDef("enable_human_behaviour_emulation", "Enable Human Behaviour Emulation"),
            # Watch Home Feed Stories
            SettingDef("enable_viewhomefeedstory", "Enable Watch Home Feed Stories"),
            SettingDef("min_viewhomefeedstory", "Home Feed Stories Min to Watch"),
            SettingDef("max_viewhomefeedstory", "Home Feed Stories Max to Watch"),
            SettingDef("min_viewhomefeedstory_delay", "Home Feed Stories Min Watch Delay (Seconds)"),
            SettingDef("max_viewhomefeedstory_delay", "Home Feed Stories Max Watch Delay (Seconds)"),
            SettingDef("percent_to_like_homefeedstory", "Home Feed Stories Percent to Like"),
            # Scroll Home Feed
            SettingDef("enable_scrollhomefeed", "Enable Scroll Home Feed"),
            SettingDef("min_scrollhomefeed", "Home Feed Min to Scroll"),
            SettingDef("max_scrollhomefeed", "Home Feed Max to Scroll"),
            SettingDef("min_scrollhomefeed_delay", "Home Feed Min Scroll Delay (Seconds)"),
            SettingDef("max_scrollhomefeed_delay", "Home Feed Max Scroll Delay (Seconds)"),
            SettingDef("percent_to_like_homefeed", "Home Feed Percent to Like"),
            # Scroll Explore Page
            SettingDef("enable_scrollexplorepage", "Enable Scroll Explore Page"),
            SettingDef("min_scrollexplorepage", "Explore Page Min Post"),
            SettingDef("max_scrollexplorepage", "Explore Page Max Post"),
            SettingDef("min_scrollexplorepage_delay", "Explore Page Min Delay (Seconds)"),
            SettingDef("max_scrollexplorepage_delay", "Explore Page Max Delay (Seconds)"),
            SettingDef("percent_to_like_explorepagepost", "Explore Page Percent to Like"),
        ],
    ),
]

# Flat set of every copyable key across all categories (for validation).
ALL_COPYABLE_KEYS: Set[str] = {
    sd.key
    for cat in SETTINGS_CATEGORIES
    for sd in cat.settings
}

# Text files that can be copied between accounts (filename, display name).
COPYABLE_TEXT_FILES: List[tuple] = [
    ("name_must_include.txt", "Follow name filter (include)"),
    ("name_must_not_include.txt", "Follow name filter (exclude)"),
    ("name_must_include_likes.txt", "Like name filter (include)"),
    ("name_must_not_include_likes.txt", "Like name filter (exclude)"),
]


@dataclass
class SettingsSnapshot:
    """All copyable settings for one account, read from settings.db."""
    account_id: int
    username: str
    device_id: str
    device_name: Optional[str]
    values: dict  # key -> value (from COPYABLE_SETTINGS keys)
    raw_json: Optional[dict] = None  # full JSON blob (for reference, never written)
    error: Optional[str] = None
    text_files: Optional[dict] = None  # filename -> content (None if not read)


@dataclass
class SettingsDiffEntry:
    """One setting key comparison: source value vs. target value."""
    key: str
    display_name: str
    source_value: object
    target_value: object
    is_different: bool  # True if source != target


@dataclass
class SettingsDiff:
    """Full diff for one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    entries: List[SettingsDiffEntry]
    different_count: int = 0  # how many entries have is_different=True


@dataclass
class SettingsCopyResult:
    """Result of copying settings to one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    success: bool
    backed_up: bool
    keys_written: List[str]
    error: Optional[str] = None


@dataclass
class SettingsCopyBatchResult:
    """Aggregate result for the entire copy operation."""
    source_username: str
    total_targets: int
    success_count: int
    fail_count: int
    results: List[SettingsCopyResult]
