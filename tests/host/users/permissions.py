def check_user_permission(user, model, action):
    return user.is_superuser or user.has_perm(
        f"{model._meta.app_label}.{action}_{model._meta.model_name}"
    )


def check_user_role(user, role, action):
    return user.is_superuser or getattr(user, "test_roles", {}).get(f"{role}.{action}", False)
