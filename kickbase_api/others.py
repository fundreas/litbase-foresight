from kickbase_api.config import get_base_url, get_json_with_token

# All other functions that don't fit anywhere else

def get_all_teams(token, competition_id):
    """Get all teams in a competition."""

    url = f"{get_base_url()}/competitions/{competition_id}/table"
    data = get_json_with_token(url, token)

    teams = [
        {
            "team_id": item.get("tid"),   # Team-ID
            "team_name": item.get("tn")   # Team Name
        }
        for item in data.get("it", [])
    ]

    return teams
