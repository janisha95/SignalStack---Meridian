"""
Meridian Factor Registry — loads factor_registry.json and returns active features.

Usage in any training script:
    from factor_registry import get_active_features, get_feature_groups
    
    features = get_active_features()          # Returns list of enabled feature names
    groups = get_feature_groups()             # Returns dict of group_name -> features
    features = get_active_features(exclude_groups=['options', 'volume_misc'])
    features = get_active_features(only_groups=['technical_core', 'momentum', 'fundamental'])
"""

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "factor_registry.json"


def load_registry(path=None):
    """Load the factor registry JSON."""
    p = Path(path) if path else REGISTRY_PATH
    if not p.exists():
        raise FileNotFoundError(f"Factor registry not found at {p}")
    return json.loads(p.read_text())


def get_feature_groups(path=None):
    """Returns dict of {group_name: {enabled, description, features}}."""
    reg = load_registry(path)
    return reg.get("groups", {})


def get_active_features(path=None, only_groups=None, exclude_groups=None):
    """
    Returns flat list of feature names from all enabled groups.
    
    Args:
        path: Override path to factor_registry.json
        only_groups: If set, only include features from these groups (ignore enabled flag)
        exclude_groups: If set, exclude features from these groups
    
    Returns:
        List of feature name strings
    """
    groups = get_feature_groups(path)
    features = []
    
    for name, group in groups.items():
        # Filter by only_groups
        if only_groups is not None:
            if name not in only_groups:
                continue
        else:
            # Use enabled flag
            if not group.get("enabled", False):
                continue
        
        # Filter by exclude_groups
        if exclude_groups and name in exclude_groups:
            continue
        
        for f in group.get("features", []):
            if f not in features:  # Deduplicate
                features.append(f)
    
    return features


def print_registry_status(path=None):
    """Pretty-print the registry status."""
    groups = get_feature_groups(path)
    total_enabled = 0
    total_disabled = 0
    
    print("=" * 60)
    print("MERIDIAN FACTOR REGISTRY")
    print("=" * 60)
    
    for name, group in groups.items():
        enabled = group.get("enabled", False)
        features = group.get("features", [])
        status = "ON " if enabled else "OFF"
        icon = "✅" if enabled else "❌"
        desc = group.get("description", "")
        
        if enabled:
            total_enabled += len(features)
        else:
            total_disabled += len(features)
        
        print(f"  {icon} {name:25s} [{status}] {len(features):2d} features — {desc}")
    
    print(f"\n  Total enabled:  {total_enabled} features")
    print(f"  Total disabled: {total_disabled} features")
    print(f"  Active list: {get_active_features(path)}")


if __name__ == "__main__":
    print_registry_status()
