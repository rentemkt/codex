//! Named permission choices in the shared picker, using the server catalog and existing actions.

use super::permission_i18n;
use super::*;
use crate::permission_discovery::PermissionDiscovery;
use codex_protocol::models::BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS;
use codex_protocol::models::BUILT_IN_PERMISSION_PROFILE_WORKSPACE;

pub(super) fn permission_preset_description(preset: &ApprovalPreset) -> &'static str {
    match preset.id {
        "read-only" => "Read workspace files, with approval required for edits or internet access",
        "auto" => {
            "Read and edit workspace files and run commands, with approval required for internet access or edits outside the workspace"
        }
        "full-access" => {
            "Use with caution: Codex can edit files outside this workspace and access the internet without approval"
        }
        _ => preset.description,
    }
}

pub(crate) fn auto_review_available(config: &Config) -> bool {
    cyber_model_approval_reviewer(config) == Some(ApprovalsReviewer::AutoReview)
}

pub(crate) fn cyber_model_approval_reviewer(config: &Config) -> Option<ApprovalsReviewer> {
    let requirements = config.config_layer_stack.requirements();
    if requirements
        .approval_policy
        .can_set(&AskForApproval::OnRequest.to_core())
        .is_err()
    {
        return None;
    }

    let reviewer = if config.features.enabled(Feature::GuardianApproval)
        && requirements
            .approvals_reviewer
            .can_set(&ApprovalsReviewer::AutoReview)
            .is_ok()
    {
        ApprovalsReviewer::AutoReview
    } else {
        ApprovalsReviewer::User
    };
    requirements
        .approvals_reviewer
        .can_set(&reviewer)
        .is_ok()
        .then_some(reviewer)
}

impl ChatWidget {
    pub(super) fn try_select_permission_profile(
        &mut self,
        discovery: &PermissionDiscovery,
        profile_id: &str,
        requested_approval_policy: Option<AskForApproval>,
        requested_reviewer: Option<ApprovalsReviewer>,
    ) -> bool {
        let reviewer = match profile_id {
            ":approve-for-me" if !self.config.features.enabled(Feature::GuardianApproval) => {
                self.add_error_message(
                    crate::i18n::tr!("permissions-approve-for-me-unavailable", "Approve for me is unavailable. Run `/permissions` to see available profiles.").into(),
                );
                return false;
            }
            ":approve-for-me" => ApprovalsReviewer::AutoReview,
            _ => ApprovalsReviewer::User,
        };
        let profile_id = match profile_id {
            ":ask-for-approval" | ":approve-for-me" => BUILT_IN_PERMISSION_PROFILE_WORKSPACE,
            id => id,
        };
        let Some(profile) = discovery
            .profiles
            .iter()
            .find(|profile| profile.id == profile_id)
        else {
            self.add_error_message(crate::i18n::tr_format!("permissions-unknown-profile", "Unknown permission profile `{profile_id}`. Run `/permissions` to see available profiles.", profile_id = profile_id));
            return false;
        };
        let preset = builtin_approval_presets()
            .into_iter()
            .find(|preset| preset.active_permission_profile.id == profile_id);
        let approval_policy = requested_approval_policy.or_else(|| {
            preset
                .as_ref()
                .map(|preset| AskForApproval::from(preset.approval))
        });
        let approvals_reviewer = requested_reviewer.or_else(|| preset.as_ref().map(|_| reviewer));
        if approvals_reviewer == Some(ApprovalsReviewer::AutoReview)
            && !self.config.features.enabled(Feature::GuardianApproval)
        {
            self.add_error_message(
                "Approve for me is unavailable. Run `/permissions` to see available profiles."
                    .into(),
            );
            return false;
        }
        if let Some(reason) = discovery.disabled_reason(
            profile_id,
            approval_policy,
            approvals_reviewer.map(Into::into),
        ) {
            self.add_error_message(crate::i18n::tr_format!(
                "permissions-profile-unavailable",
                "Permission profile `{profile_id}` is unavailable: {reason}.",
                profile_id = profile_id,
                reason = reason
            ));
            return false;
        }
        let display_label = preset.as_ref().map_or_else(
            || profile.id.clone(),
            |preset| match (preset.id, approvals_reviewer) {
                ("auto", Some(ApprovalsReviewer::AutoReview)) => {
                    permission_i18n::approve_for_me_label()
                }
                ("auto", _) => permission_i18n::ask_for_approval_label(),
                _ => permission_i18n::preset_label(preset),
            },
        );
        let selection = PermissionProfileSelection {
            profile_id: profile_id.to_string(),
            approval_policy,
            approvals_reviewer,
            display_label: display_label.to_string(),
        };
        if let Some(preset) = preset {
            let Some(action) = self
                .permission_mode_actions(
                    &preset,
                    display_label,
                    approvals_reviewer.unwrap_or(reviewer),
                    /*profile_selection*/ Some(selection),
                    /*return_to_permissions*/ true,
                )
                .into_iter()
                .next()
            else {
                return false;
            };
            action(&self.app_event_tx);
            return true;
        }
        self.app_event_tx
            .send(AppEvent::SelectPermissionProfile(selection));
        true
    }

    pub(super) fn open_permission_profiles_popup(&mut self, discovery: PermissionDiscovery) {
        let active_profile_id = self
            .config
            .permissions
            .active_permission_profile()
            .map(|profile| profile.id);
        let presets = builtin_approval_presets();
        let Some(read_only) = presets.iter().find(|preset| preset.id == "read-only") else {
            self.add_error_message(
                "Internal error: missing the 'read-only' approval preset.".to_string(),
            );
            return;
        };
        let Some(default) = presets.iter().find(|preset| preset.id == "auto") else {
            self.add_error_message(
                "Internal error: missing the 'auto' approval preset.".to_string(),
            );
            return;
        };
        let Some(full_access) = presets.iter().find(|preset| preset.id == "full-access") else {
            self.add_error_message(
                "Internal error: missing the 'full-access' approval preset.".to_string(),
            );
            return;
        };
        let mut items = vec![self.builtin_permission_mode_selection_item(
            &discovery,
            default,
            ":workspace",
            permission_i18n::preset_description(default),
            AskForApproval::from(default.approval),
            ApprovalsReviewer::User,
        )];
        if self.config.features.enabled(Feature::GuardianApproval) {
            items.push(self.builtin_permission_mode_selection_item(
                &discovery,
                default,
                ":workspace",
                permission_i18n::auto_review_description(),
                AskForApproval::OnRequest,
                ApprovalsReviewer::AutoReview,
            ));
        }
        items.push(self.builtin_permission_mode_selection_item(
            &discovery,
            full_access,
            BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS,
            permission_i18n::preset_description(full_access),
            AskForApproval::from(full_access.approval),
            ApprovalsReviewer::User,
        ));
        items.push(self.builtin_permission_mode_selection_item(
            &discovery,
            read_only,
            ":read-only",
            permission_i18n::preset_description(read_only),
            AskForApproval::from(read_only.approval),
            ApprovalsReviewer::User,
        ));
        items.extend(
            discovery
                .profiles
                .iter()
                .filter(|profile| !profile.id.starts_with(':'))
                .map(|profile| {
                    let description = profile.description.clone().unwrap_or_else(|| {
                        permission_i18n::text(
                            "permissions-configured-profile-description",
                            "Configured permission profile.",
                        )
                    });
                    Self::permission_profile_selection_item(
                        &profile.id,
                        &profile.id,
                        &description,
                        active_profile_id.as_deref(),
                        discovery.disabled_reason(
                            &profile.id,
                            /*approval*/ None,
                            /*reviewer*/ None,
                        ),
                    )
                }),
        );

        if discovery.profiles.is_empty() {
            items.clear();
        }
        if let Some(id) = active_profile_id.as_deref()
            && !discovery.profiles.iter().any(|profile| profile.id == id)
            && !items.iter().any(|item| item.is_current)
        {
            items.push(Self::permission_profile_selection_item(
                id,
                id,
                crate::i18n::tr!("permissions-current-profile", "Current permission profile"),
                Some(id),
                Some(
                    crate::i18n::tr!(
                        "permissions-unavailable-on-server",
                        "Not available on this server"
                    )
                    .to_string(),
                ),
            ));
        }
        self.bottom_pane.show_selection_view(SelectionViewParams {
            view_id: Some(super::permission_discovery::VIEW_ID),
            items,
            title: Some(permission_i18n::text(
                "permissions-picker-title",
                "Update Model Permissions",
            )),
            subtitle: discovery.profiles.is_empty().then(|| {
                crate::i18n::tr!(
                    "permissions-no-profiles-returned",
                    "No permission profiles returned by the server."
                )
                .to_string()
            }),
            ..SelectionViewParams::picker()
        });
    }

    fn builtin_permission_mode_selection_item(
        &self,
        discovery: &PermissionDiscovery,
        preset: &ApprovalPreset,
        id: &str,
        description: String,
        approval_policy: AskForApproval,
        approvals_reviewer: ApprovalsReviewer,
    ) -> SelectionItem {
        let label = match (preset.id, approvals_reviewer) {
            ("auto", ApprovalsReviewer::AutoReview) => permission_i18n::approve_for_me_label(),
            ("auto", ApprovalsReviewer::User) => permission_i18n::ask_for_approval_label(),
            _ => permission_i18n::preset_label(preset),
        };
        let active_profile_id = self
            .config
            .permissions
            .active_permission_profile()
            .map(|profile| profile.id);
        let current_approval =
            AskForApproval::from(self.config.permissions.approval_policy.value());
        let current_reviewer = self.config.approvals_reviewer;
        let profile_id = id.to_string();
        let selection = PermissionProfileSelection {
            profile_id,
            approval_policy: Some(approval_policy),
            approvals_reviewer: Some(approvals_reviewer),
            display_label: label.clone(),
        };
        SelectionItem {
            name: label.clone(),
            description: Some(description),
            is_current: active_profile_id.as_deref().map_or_else(
                || {
                    Self::preset_matches_current(
                        current_approval,
                        self.config.permissions.permission_profile(),
                        self.config.cwd.as_path(),
                        preset,
                    )
                },
                |active| active == id,
            ) && current_approval == approval_policy
                && current_reviewer == approvals_reviewer,
            actions: self.permission_mode_actions(
                preset,
                label,
                approvals_reviewer,
                Some(selection),
                /*return_to_permissions*/ true,
            ),
            dismiss_on_select: true,
            disabled_reason: discovery.disabled_reason(
                id,
                Some(approval_policy),
                Some(approvals_reviewer.into()),
            ),
            ..Default::default()
        }
    }

    fn permission_profile_selection_item(
        label: &str,
        id: &str,
        description: &str,
        active_profile_id: Option<&str>,
        disabled_reason: Option<String>,
    ) -> SelectionItem {
        let id_for_action = id.to_string();
        let selection = PermissionProfileSelection {
            profile_id: id_for_action.clone(),
            approval_policy: None,
            approvals_reviewer: None,
            display_label: id_for_action,
        };
        SelectionItem {
            name: label.to_string(),
            description: Some(description.to_string()),
            is_current: active_profile_id == Some(id),
            actions: Self::permission_profile_selection_actions(selection),
            dismiss_on_select: true,
            disabled_reason,
            ..Default::default()
        }
    }
}
