use std::collections::BTreeMap;

use codex_protocol::ThreadId;
use ratatui::text::Line;

use super::status_line_from_segments;
use super::status_line_setup::StatusLineItem;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub(crate) enum StatusSurfacePreviewItem {
    AppName,
    ProjectName,
    ProjectRoot,
    CurrentDir,
    Hostname,
    Status,
    ThreadName,
    ThreadTitle,
    GitBranch,
    PullRequestNumber,
    BranchChanges,
    Permissions,
    ApprovalMode,
    ContextRemaining,
    ContextUsed,
    FiveHourLimit,
    WeeklyLimit,
    CodexVersion,
    ContextWindowSize,
    UsedTokens,
    TotalInputTokens,
    TotalOutputTokens,
    ThreadCredits,
    EstimatedThreadCost,
    SessionId,
    FastMode,
    Daybreak,
    RawOutput,
    WorkspaceHeadline,
    Model,
    ModelWithReasoning,
    Reasoning,
    Profile,
    Provider,
    TaskProgress,
}

impl StatusSurfacePreviewItem {
    fn placeholder(self) -> &'static str {
        match self {
            StatusSurfacePreviewItem::AppName => "codex",
            StatusSurfacePreviewItem::ProjectName => "my-project",
            StatusSurfacePreviewItem::ProjectRoot => "my-project",
            StatusSurfacePreviewItem::CurrentDir => "~/my-project/subdir",
            StatusSurfacePreviewItem::Hostname => "my-host",
            StatusSurfacePreviewItem::Status => {
                crate::i18n::tr!("status-run-state-working", "Working")
            }
            StatusSurfacePreviewItem::ThreadName => {
                crate::i18n::tr!("status-preview-thread-name", "thread name")
            }
            StatusSurfacePreviewItem::ThreadTitle => {
                crate::i18n::tr!("status-preview-thread-title", "thread title")
            }
            StatusSurfacePreviewItem::GitBranch => "feat/awesome-feature",
            StatusSurfacePreviewItem::PullRequestNumber => "PR #123",
            StatusSurfacePreviewItem::BranchChanges => "+12 -3",
            StatusSurfacePreviewItem::Permissions => {
                crate::i18n::tr!("status-permissions-workspace", "Workspace")
            }
            StatusSurfacePreviewItem::ApprovalMode => "on-request",
            StatusSurfacePreviewItem::ContextRemaining => {
                crate::i18n::tr!("status-preview-context-remaining", "Context 0% left")
            }
            StatusSurfacePreviewItem::ContextUsed => {
                crate::i18n::tr!("status-preview-context-used", "Context 0% used")
            }
            StatusSurfacePreviewItem::FiveHourLimit => {
                crate::i18n::tr!("status-preview-primary-limit", "primary 0%")
            }
            StatusSurfacePreviewItem::WeeklyLimit => {
                crate::i18n::tr!("status-preview-secondary-limit", "secondary 0%")
            }
            StatusSurfacePreviewItem::CodexVersion => "0.0.0",
            StatusSurfacePreviewItem::ContextWindowSize => {
                crate::i18n::tr!("status-preview-window", "0 window")
            }
            StatusSurfacePreviewItem::UsedTokens => {
                crate::i18n::tr!("status-preview-used", "0 used")
            }
            StatusSurfacePreviewItem::TotalInputTokens => {
                crate::i18n::tr!("status-preview-input", "0 in")
            }
            StatusSurfacePreviewItem::TotalOutputTokens => {
                crate::i18n::tr!("status-preview-output", "0 out")
            }
            StatusSurfacePreviewItem::ThreadCredits => {
                crate::i18n::tr!("status-preview-credits", "5.2 credits")
            }
            StatusSurfacePreviewItem::EstimatedThreadCost => "~$1.82",
            StatusSurfacePreviewItem::SessionId => "550e8400-e29b-41d4",
            StatusSurfacePreviewItem::FastMode => {
                crate::i18n::tr!("status-service-tier-fast", "Fast")
            }
            StatusSurfacePreviewItem::Daybreak => {
                crate::i18n::tr!("status-line-daybreak-off", "Daybreak off")
            }
            StatusSurfacePreviewItem::RawOutput => {
                crate::i18n::tr!("status-line-raw-output", "raw output")
            }
            StatusSurfacePreviewItem::WorkspaceHeadline => {
                crate::i18n::tr!("status-preview-workspace-headline", "Workspace headline")
            }
            StatusSurfacePreviewItem::Model => "gpt-5.2-codex",
            StatusSurfacePreviewItem::ModelWithReasoning => "gpt-5.2-codex medium",
            StatusSurfacePreviewItem::Reasoning => "medium",
            StatusSurfacePreviewItem::Profile => {
                crate::i18n::tr!("status-preview-profile", "profile: <name>")
            }
            StatusSurfacePreviewItem::Provider => {
                crate::i18n::tr!("status-preview-provider", "provider: <id>")
            }
            StatusSurfacePreviewItem::TaskProgress => {
                crate::i18n::tr!("status-preview-task-progress", "Tasks 0/0")
            }
        }
    }

    pub(crate) fn iter() -> impl Iterator<Item = Self> {
        [
            Self::AppName,
            Self::ProjectName,
            Self::ProjectRoot,
            Self::CurrentDir,
            Self::Hostname,
            Self::Status,
            Self::ThreadName,
            Self::ThreadTitle,
            Self::GitBranch,
            Self::PullRequestNumber,
            Self::BranchChanges,
            Self::Permissions,
            Self::ApprovalMode,
            Self::ContextRemaining,
            Self::ContextUsed,
            Self::FiveHourLimit,
            Self::WeeklyLimit,
            Self::CodexVersion,
            Self::ContextWindowSize,
            Self::UsedTokens,
            Self::TotalInputTokens,
            Self::TotalOutputTokens,
            Self::ThreadCredits,
            Self::EstimatedThreadCost,
            Self::SessionId,
            Self::FastMode,
            Self::Daybreak,
            Self::RawOutput,
            Self::WorkspaceHeadline,
            Self::Model,
            Self::ModelWithReasoning,
            Self::Reasoning,
            Self::Profile,
            Self::Provider,
            Self::TaskProgress,
        ]
        .into_iter()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PreviewValue {
    text: String,
    is_placeholder: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct StatusSurfacePreviewData {
    pub(crate) thread_id: Option<ThreadId>,
    values: BTreeMap<StatusSurfacePreviewItem, PreviewValue>,
}

impl Default for StatusSurfacePreviewData {
    fn default() -> Self {
        let mut data = Self {
            thread_id: None,
            values: BTreeMap::new(),
        };
        for item in StatusSurfacePreviewItem::iter() {
            data.set_placeholder(item, item.placeholder());
        }
        data
    }
}

impl StatusSurfacePreviewData {
    pub(crate) fn from_iter<I, V>(values: I) -> Self
    where
        I: IntoIterator<Item = (StatusSurfacePreviewItem, V)>,
        V: Into<String>,
    {
        let mut data = Self::default();
        for (item, value) in values {
            data.set_live(item, value);
        }
        data
    }

    pub(crate) fn set_live<V>(&mut self, item: StatusSurfacePreviewItem, value: V)
    where
        V: Into<String>,
    {
        self.values.insert(
            item,
            PreviewValue {
                text: value.into(),
                is_placeholder: false,
            },
        );
    }

    pub(crate) fn set_placeholder<V>(&mut self, item: StatusSurfacePreviewItem, value: V)
    where
        V: Into<String>,
    {
        if self
            .values
            .get(&item)
            .is_some_and(|value| !value.is_placeholder)
        {
            return;
        }
        self.values.insert(
            item,
            PreviewValue {
                text: value.into(),
                is_placeholder: true,
            },
        );
    }

    pub(crate) fn suppress_placeholder(&mut self, item: StatusSurfacePreviewItem) {
        if self
            .values
            .get(&item)
            .is_some_and(|value| value.is_placeholder)
        {
            self.values.remove(&item);
        }
    }

    pub(crate) fn rate_limit_item_name(
        &self,
        item: StatusSurfacePreviewItem,
        fallback: &str,
    ) -> String {
        self.live_value_for(item)
            .and_then(rate_limit_preview_copy)
            .map(|copy| copy.name)
            .unwrap_or_else(|| fallback.to_string())
    }

    pub(crate) fn rate_limit_item_description(
        &self,
        item: StatusSurfacePreviewItem,
        fallback: &str,
    ) -> String {
        self.live_value_for(item)
            .and_then(rate_limit_preview_copy)
            .map(|copy| copy.description)
            .unwrap_or_else(|| fallback.to_string())
    }

    pub(crate) fn value_for(&self, item: StatusSurfacePreviewItem) -> Option<&str> {
        self.values.get(&item).map(|value| value.text.as_str())
    }

    fn live_value_for(&self, item: StatusSurfacePreviewItem) -> Option<&str> {
        self.values
            .get(&item)
            .filter(|value| !value.is_placeholder)
            .map(|value| value.text.as_str())
    }

    pub(crate) fn status_line_for_items<I>(
        &self,
        items: I,
        use_theme_colors: bool,
    ) -> Option<Line<'static>>
    where
        I: IntoIterator<Item = StatusLineItem>,
    {
        let segments = items.into_iter().filter_map(|item| {
            self.value_for(item.preview_item())
                .map(|value| (item, value.to_string()))
        });
        status_line_from_segments(segments, use_theme_colors, self.thread_id)
    }
}

struct RateLimitPreviewCopy {
    name: String,
    description: String,
}

fn rate_limit_preview_copy(value: &str) -> Option<RateLimitPreviewCopy> {
    let value = value.trim_start();
    if value.starts_with("secondary usage ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-secondary-usage-name", None, || {
                "secondary-usage-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-secondary-usage-description",
                None,
                || {
                    "Remaining usage on the secondary usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("usage ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-primary-usage-name", None, || {
                "usage-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-primary-usage-description",
                None,
                || {
                    "Remaining usage on the primary usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("5h ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-five-hour-name", None, || {
                "five-hour-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-five-hour-description",
                None,
                || {
                    "Remaining usage on the 5-hour usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("daily ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-daily-name", None, || {
                "daily-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-daily-description",
                None,
                || {
                    "Remaining usage on the daily usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("weekly ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-weekly-name", None, || {
                "weekly-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-weekly-description",
                None,
                || {
                    "Remaining usage on the weekly usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("monthly ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-monthly-name", None, || {
                "monthly-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-monthly-description",
                None,
                || {
                    "Remaining usage on the monthly usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else if value.starts_with("annual ") {
        Some(RateLimitPreviewCopy {
            name: crate::i18n::global().text("status-surface-annual-name", None, || {
                "annual-limit".to_string()
            }),
            description: crate::i18n::global().text(
                "status-surface-annual-description",
                None,
                || {
                    "Remaining usage on the annual usage limit (omitted when unavailable)"
                        .to_string()
                },
            ),
        })
    } else {
        None
    }
}
