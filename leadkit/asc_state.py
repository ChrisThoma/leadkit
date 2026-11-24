"""Whether App Store Connect will take listing changes on a version.

A version can be edited only before it's submitted or after it's rejected. A push
that runs after the version was submitted has every one of its creations refused,
one per language and field.
"""
import json, subprocess

EDITABLE = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY"}


def version_problem(app_id, version, run=subprocess.run):
    """None when `version` can take listing changes, else one line saying why not."""
    r = run(["asc", "versions", "list", "--app", str(app_id), "--platform", "IOS", "--paginate", "--output", "json"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return f"couldn't read {version}'s state from App Store Connect: {(r.stderr or r.stdout).strip()[:200]}"
    try:
        rows = json.loads(r.stdout).get("data", [])
    except ValueError:
        return f"couldn't read {version}'s state from App Store Connect: not JSON"
    for row in rows:
        a = row.get("attributes", {})
        if a.get("versionString") == version and a.get("platform", "IOS") == "IOS":
            state = a.get("appVersionState") or a.get("appStoreState")
            if state in EDITABLE:
                return None
            return (f"{version} is {state} in App Store Connect and won't take new languages or listing "
                    f"changes. Use the next version, or wait for a rejection.")
    return f"App Store Connect has no {version} yet. Create the version first."
