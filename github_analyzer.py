import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import time

def get_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        read=5,
        connect=5,
        backoff_factor=1,
        status_forcelist=[403, 429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

session = get_session()

def get_rate_limit_remaining(response):
    return int(response.headers.get('X-RateLimit-Remaining', 1))

def get_headers(token=None):
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'GitHubAnalyzerScript/1.0'
    }
    if token:
        headers['Authorization'] = f'token {token}'
    return headers

def get_repos(profile_name, token=None):
    url = f"https://api.github.com/users/{profile_name}/repos"
    headers = get_headers(token)
    
    repos = []
    page = 1
    while True:
        print(f"Fetching page {page} of repos for {profile_name}...")
        params = {'per_page': 100, 'page': page}
        
        try:
            response = session.get(url, headers=headers, params=params, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"Connection error while fetching repos: {e}")
            break
            
        if response.status_code == 403 and 'rate limit' in response.text.lower():
            print("WARNING: GitHub API Rate limit exceeded!")
            break
        elif response.status_code != 200:
            print(f"Error fetching repos: {response.status_code} - {response.text}")
            break
            
        data = response.json()
        if not data:
            break
            
        repos.extend(data)
        
        remaining = get_rate_limit_remaining(response)
        if remaining <= 1:
            print("WARNING: GitHub API Rate limit almost exceeded. Pausing...")
            print("Stopping repo fetch early due to rate limits.")
            break

        page += 1
        
    return repos

def get_readme(owner, repo, token=None):
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    headers = get_headers(token)
        
    try:
        response = session.get(url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"Connection error while fetching README: {e}")
        return "Connection error.", True
        
    if response.status_code == 403 and 'rate limit' in response.text.lower():
        print("WARNING: GitHub API Rate limit exceeded!")
        return "Rate limit exceeded.", False
        
    if response.status_code == 200:
        data = response.json()
        if 'content' in data:
            try:
                content = base64.b64decode(data['content']).decode('utf-8')
                return content, True
            except Exception:
                return "Error decoding README.", True
    return "No README found.", True

def get_profile_info(profile_name, token=None):
    url = f"https://api.github.com/users/{profile_name}"
    headers = get_headers(token)
    
    try:
        response = session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Connection error while fetching profile info: {e}")
        
    return {}

def analyze_profile(profile_url, token=None, limit_repos=None):
    profile_name = profile_url.rstrip('/').split('/')[-1]
    
    profile_info = get_profile_info(profile_name, token)
    total_public_repos = profile_info.get('public_repos', 'Unknown')
    
    repos = get_repos(profile_name, token)
    
    if limit_repos:
        repos = repos[:limit_repos]
        print(f"Limiting to {limit_repos} repositories for analysis.")
    
    md_filename = f"{profile_name}_analysis.md"
    
    total_size_kb = sum(repo.get('size', 0) for repo in repos)
    total_size_mb = round(total_size_kb / 1024, 2)
    total_size_gb = round(total_size_mb / 1024, 2)
    
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(f"# Analysis for GitHub Profile: {profile_name}\n\n")
        f.write(f"Profile URL: {profile_url}\n")
        f.write(f"Total Public Repositories (on profile): {total_public_repos}\n")
        f.write(f"Total Repositories Extracted: {len(repos)}\n")
        f.write(f"Total Space Required (For these repos): {total_size_kb} KB | {total_size_mb} MB | {total_size_gb} GB\n\n")
        
        f.write("## Repositories Summary Table\n\n")
        f.write("| Repository Name | Space Requirement (KB) | Space Requirement (MB) | Description |\n")
        f.write("|---|---|---|---|\n")
        
        for repo in repos:
            name = repo.get('name', 'N/A')
            size_kb = repo.get('size', 0)
            size_mb = round(size_kb / 1024, 2)
            desc = repo.get('description', '') or 'No description'
            # Cleanup description for markdown table formatting
            desc = desc.replace('\n', ' ').replace('\r', '').replace('|', '-')
            f.write(f"| {name} | {size_kb} KB | {size_mb} MB | {desc} |\n")
            
        f.write("\n## Detailed Repository Agendas (from README files)\n\n")
        
        for repo in repos:
            name = repo.get('name', 'N/A')
            print(f"Fetching README for {name}...")
            readme_content, continue_fetch = get_readme(profile_name, name, token)
            
            f.write(f"### {name}\n\n")
            if readme_content in ["No README found.", "Error decoding README.", "Rate limit exceeded.", "Connection error."]:
                f.write(f"*{readme_content}*\n\n")
            else:
                # Limit the readme text length slightly to avoid massive files (first 2500 characters)
                preview = readme_content[:2500] + ("...\n\n*(Truncated for length)*" if len(readme_content) > 2500 else "")
                f.write(f"```markdown\n{preview}\n```\n\n")
                
            if not continue_fetch:
                f.write("> **Note**: Rate limit exceeded, stopped fetching READMEs.\n")
                print("Stopping README fetches due to rate limits.")
                break
                
            if not token:
                time.sleep(0.5)

    print(f"Analysis saved to {md_filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze GitHub profile repositories.')
    parser.add_argument('--urls', nargs='+', help='List of GitHub profile URLs to analyze', required=True)
    parser.add_argument('--token', help='GitHub Personal Access Token (recommended to avoid rate limits)', default=None)
    parser.add_argument('--limit', type=int, help='Limit number of repos to analyze per profile (useful for large orgs)', default=None)
    
    args = parser.parse_args()
    
    for url in args.urls:
        print(f"\n{'='*50}\nAnalyzing {url}...\n{'='*50}")
        analyze_profile(url, args.token, args.limit)
