import json

import eln_common.fill_info as fill_info


def dict_simplify(d: dict) -> dict:
    """
    param d: dict The dictionary, as pulled from ELN. extra_fields still as strings and stuff
    Remove unnecessary keys from the dictionary and reformat to be sent to UI
    """
    return_dict = {}
    return_dict['title'] = d['title']
    return_dict['extra_fields'] = json.loads(d['metadata'])['extra_fields']
    return return_dict


def dict_complexify(d: dict) -> dict:
    """
    inverse of dict_simplify
    """
    return_dict = {}
    return_dict['title'] = d['title']
    return_dict['body'] = d['body']
    return_dict['category'] = d['category']  # NOTE this is an integer, not a string !
    return_dict['metadata'] = json.dumps({'extra_fields': d['extra_fields']})
    return return_dict


def search_and_fill(template: dict, CAS: str) -> dict:
    template['CAS'] = CAS
    template = dict_complexify(template)
    template['title'] = CAS
    return dict_simplify(fill_info.get_filled_dictionary(template))
