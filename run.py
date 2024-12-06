import sys, os, datetime, argparse
import pickle as pkl
from time import sleep

import pandas as pd
from tqdm import tqdm

from errors import *
from contents import get_gscholar_contents, get_citations, get_papers_list

# from habanero import Crossref
import requests
from multiprocessing import Pool, get_context, Manager
import json
cpu_count = os.cpu_count()
# Solve conflict between raw_input and input on Python 2 and Python 3
if sys.version[0]=="3": raw_input=input

# Default Parameters
CSVPATH = '.' # Current folder

def get_command_line_args():
    now = datetime.datetime.now()

    # Command line arguments
    parser = argparse.ArgumentParser(description='Arguments')
    parser.add_argument('--conference', type=str, required=True, help='Conference name to sort papers.')
    parser.add_argument('--year', type=int, required=True, help='Conference year to sort papers.')
    parser.add_argument('--month', type=int, help='Conference month. (Optinal)')
    parser.add_argument('--csvpath', type=str, help='Path to save the exported csv file. By default it is the current folder')

    # Parse and read arguments and assign them to variables if exists
    args, _ = parser.parse_known_args()

    conference_dict = {'cvpr': 'CVPR',
                       'iccv': 'ICCV',
                       'iclr': 'ICLR',
                       'icml': 'ICML',
                       'eccv': 'ECCV',
                       'icra': 'ICRA',
                       'nips': 'NeurIPS',
                       'neurips': 'NeurIPS'}
    if args.conference.lower() not in conference_dict.keys():
        raise ValueError("Conference must be one of {}".format(list(conference_dict.keys())))
    conference = conference_dict[args.conference.lower()]

    year = args.year
    month = None
    if args.month:
        if args.month < 1 or args.month > 12:
            raise ValueError("Month must be in range [1, ..., 12].")
            
        if year == now.year and args.month > now.month:
            raise ValueError("Month must be <= {}.".format(now.month))

        month = args.month

    csvpath = CSVPATH
    if args.csvpath:
        csvpath = args.csvpath

    return conference, year, month, csvpath

def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = raw_input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")


def save_checkpoint(conference, year, authors, titles, links, idx, citations, etc):
    if idx != 0:
        with open('./temp/backup.pkl', 'wb') as f:
            pkl.dump({'conference': conference,
                      'year': year,
                      'authors': authors,
                      'titles': titles,
                      'links': links,
                      'idx': idx,
                      'citations': citations,
                      'etc': etc}, f)

def restore_checkpoint():
    with open('./temp/backup.pkl', 'rb') as f:
        data = pkl.load(f)
    
    return data['conference'], data['year'], data['authors'], data['titles'], data['links'], data['idx'], data['citations'], data['etc']

def get_doi(title):
    url = 'https://api.crossref.org/works'
    params = {'query.title': title, 'rows': 1, 'query.bibliographic': title}
    response = requests.get(url, params=params)
    try:
        response.raise_for_status()
        data = response.json()
        # breakpoint()
        if data['message']['total-results'] == 0:
            return None
        else:
            return data['message']['items'][0]['DOI']
    except requests.exceptions.HTTPError as e:
        print(f"DOI Error: {e}, {title}")
        return None
    # breakpoint()
    # for using semanticscholar, we need to first query the paper title to get the paperid
    # with the paper id, we query again to get the doi
    # url = 'https://api.semanticscholar.org/graph/v1/paper/search/match?query=' + title
    # params = {'limit': 1, 'fields': 'title'}
    # response = requests.get(url, params=params)
    # while True:
    #     try:
    #         # if the error is 429, we wait for 1 second and try again
    #         response.raise_for_status()
    #         data = response.json()
    #     except requests.exceptions.HTTPError as e:
    #         if response.status_code == 429:
    #             print("Too many requests. Waiting for 1 second.")
    #             sleep(1)
    #             response = requests.get(url, params=params)
    #             continue
    #         else:
    #             break
    # if len(data['data']) == 0:
    #     print(f"Title not found: {title}")
    #     return None
    # url = 'https://api.semanticscholar.org/graph/v1/paper/' + data['data'][0]['paperId']
    # params = {'fields': 'externalIds'}
    # response = requests.get(url, params=params)
    # while True:
    #     try:
    #         response.raise_for_status()
    #         doi_data = response.json()
    #         if 'DOI' not in doi_data['externalIds']:
    #             print(f"DOI not found for {title}")
    #             return None
    #         return doi_data['externalIds']['DOI']
    #     except requests.exceptions.HTTPError as e:
    #         if response.status_code == 429:
    #             print("Too many requests. Waiting for 1 second.")
    #             sleep(1)
    #             response = requests.get(url, params=params)
    #             continue
    #         else:
    #             return None
    
def get_count(title):
    url = 'https://api.crossref.org/works'
    params = {'query.title': title, 'rows': 1, 'query.bibliographic': title}
    response = requests.get(url, params=params)
    try:
        response.raise_for_status()
        data = response.json()
        # breakpoint()
        if data['message']['total-results'] == 0:
            return title, -1
        else:
            return title, data['message']['items'][0].get('is-referenced-by-count', -1)
    except requests.exceptions.HTTPError as e:
        print(f"DOI Error: {e}, {title}")
        return title, -1
    
def get_citation_count(doi):
    url = f'https://opencitations.net/index/api/v2/citation-count/doi:{doi}'
    headers = {'Accept': 'application/json', "authorization": '017f75ef-751f-4eee-8002-52773db6bc36'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    return data[0]['count']

def get_citations_from_title(title):
    
    doi = get_doi(title)
    if doi is None:
        print(f"DOI not found for {title }")
        return title, -1
    return title,get_citation_count(doi)

def main():
    GSCHOLAR_URL = "https://scholar.google.com/scholar?hl=en&as_sdt=0%2C5&q={}&num=1"
    
    # Variables
    conference, year, month, csvpath = get_command_line_args()

    if month is None:
        print("Please provide month for \"cit/month\" information.")

    # Accumul.
    start_idx = 0
    citations = []
    etc = []
    print("Loading {} {} results".format(conference, year))
    authors, titles, links = get_papers_list(conference, year)
    print("Found {:d} papers.".format(len(authors)))
    assert len(authors) == len(titles) == len(links) != 0, f"No {conference} papers found in year {year}."
    
    if os.path.exists(f'./temp/{conference}_{year}_completed.json'):
        information_dict = json.load(open(f'./temp/{conference}_{year}_completed.json'))
    else:
        information_dict = {title :{'authors' : author , 'link' : link} for title, author, link in zip(titles, authors, links)}
    not_processed = [title for title in titles if 'citations' not in information_dict[title].keys()]
    print(f"Skipping already done {len(titles) - len(not_processed)} papers of total {len(titles)} papers.")
    p = get_context("spawn").Pool(5)
    with tqdm(range(start_idx, len(not_processed))) as pbar:
        for cit in p.imap_unordered(get_count, not_processed):
            information_dict[cit[0]]['citations'] = cit[1]
            information_dict[cit[0]]['etc'] = ''
            pbar.update()
            # for every 100 papers, save the progress
            if pbar.n % 100 == 0:
                try:
                    json.dump(information_dict, open(f'./temp/{conference}_{year}_completed.json', 'w'))
                except TypeError:
                    breakpoint()
    p.close()
    p.join()
    
    authors = [information_dict[title]['authors'] for title in titles]
    links = [information_dict[title]['link'] for title in titles]
    citations = [-1 if 'citations' not in information_dict[title].keys() else int(information_dict[title]['citations']) for title in titles]
    etc = ['' if 'etc' not in information_dict[title].keys() else information_dict[title]['etc'] for title in titles]
    # Create a dataset and sort by the number of citations
    data = pd.DataFrame(list(zip(authors, titles, citations, links, etc)), index = [i+1 for i in range(len(authors))],
                        columns=['Author', 'Title', 'Citations', 'Source', 'Etc'])
    data.index.name = 'ID'

    # Sort by Citations
    data_ranked = data.sort_values(by='Citations', ascending=False)

    # Add columns with number of citations per year
    now = datetime.datetime.now()
    year_diff = now.year - year
    data_ranked.insert(4, 'cit/year', data_ranked['Citations'] / (year_diff + 1))
    data_ranked['cit/year'] = data_ranked['cit/year'].round(0).astype(int)

    # Add columns with number of citations per month 
    if month is not None:
        month_diff = now.month - month + 12 * year_diff
        data_ranked.insert(5, 'cit/month', data_ranked['Citations'] / (month_diff + 1))
        data_ranked['cit/month'] = data_ranked['cit/month'].round(0).astype(int)

    print(data_ranked)

    # Save results
    data_ranked.to_csv(os.path.join(csvpath, '{}{}'.format(conference, year)+'.csv'), encoding='utf-8') # Change the path

if __name__ == '__main__':
        main()
