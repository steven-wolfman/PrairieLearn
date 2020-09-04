import prairielearn as pl
import lxml.html
import chevron
import json
from io import StringIO
import csv
import hashlib


def get_file_names_as_array(raw_file_names):
    raw_file_names = StringIO(raw_file_names)
    reader = csv.reader(raw_file_names, delimiter=',', escapechar='\\', quoting=csv.QUOTE_NONE, skipinitialspace=True, strict=True)
    for row in reader:
        # Assume only one row
        return row


# Each pl-file-upload element is uniquely identified by the SHA1 hash of its
# file_names attribute
def get_answer_name(file_names):
    return '_file_upload_{0}'.format(hashlib.sha1(file_names.encode('utf-8')).hexdigest())


def add_format_error(data, error_string):
    if '_files' not in data['format_errors']:
        data['format_errors']['_files'] = []
    data['format_errors']['_files'].append(error_string)


def prepare(element_html, data):
    element = lxml.html.fragment_fromstring(element_html)
    required_attribs = ['file-names']
    optional_attribs = []
    pl.check_attribs(element, required_attribs, optional_attribs)

    if '_required_file_names' not in data['params']:
        data['params']['_required_file_names'] = []
    file_names = get_file_names_as_array(pl.get_string_attrib(element, 'file-names'))
    data['params']['_required_file_names'].extend(file_names)


def render(element_html, data):
    if data['panel'] != 'question':
        return ''

    element = lxml.html.fragment_fromstring(element_html)
    uuid = pl.get_uuid()
    raw_file_names = pl.get_string_attrib(element, 'file-names', '')
    file_names = get_file_names_as_array(raw_file_names)
    file_names_json = json.dumps(file_names, allow_nan=False)
    answer_name = get_answer_name(raw_file_names)

    html_params = {'name': answer_name, 'file_names': file_names_json, 'uuid': uuid}

    files = data['submitted_answers'].get('_files', None)
    file_storage_s3 = data['submitted_answers'].get('_file_storage_s3', None)

    if files is not None:
        # Filter out any files not part of this element's file_names
        filtered_files = [x for x in files if x.get('name', '') in file_names]
        html_params['has_files'] = True
        html_params['files'] = json.dumps(filtered_files, allow_nan=False)

        if file_storage_s3 is not None:
            s3_files = file_storage_s3.get(answer_name, [])
            s3_filtered_files = [x for x in s3_files if x.get('name', '') in file_names]
            html_params['s3_files'] = json.dumps(s3_filtered_files, allow_nan=False)
    else:
        html_params['has_files'] = False

    with open('pl-file-upload.mustache', 'r', encoding='utf-8') as f:
        html = chevron.render(f, html_params).strip()

    return html


def parse(element_html, data):
    element = lxml.html.fragment_fromstring(element_html)
    raw_file_names = pl.get_string_attrib(element, 'file-names', '')
    required_file_names = get_file_names_as_array(raw_file_names)
    answer_name = get_answer_name(raw_file_names)
    # Get submitted answer or return parse_error if it does not exist
    files = data['submitted_answers'].get(answer_name, None)
    s3_files = data['submitted_answers'].get('_file_storage_s3', {}).get(answer_name, [])

    # We will store the files in the submitted_answer["_files"] key,
    # so delete the original submitted answer format to avoid
    # duplication
    del data['submitted_answers'][answer_name]

    if files is not None:

        try:
            parsed_files = json.loads(files)
        except ValueError:
            add_format_error(data, 'Could not parse submitted files.')

        # Filter out any files that were not listed in file_names
        parsed_files = [x for x in parsed_files if x.get('name', '') in required_file_names]

        if data['submitted_answers'].get('_files', None) is None:
            data['submitted_answers']['_files'] = parsed_files
        elif isinstance(data['submitted_answers'].get('_files', None), list):
            data['submitted_answers']['_files'].extend(parsed_files)
        else:
            add_format_error(data, '_files was present but was not an array.')

        # Validate that all required files are present from db or s3 source
        missing_files = []

        if parsed_files is not None:
            db_submitted_file_names = [x.get('name', '') for x in parsed_files]
            missing_files = [x for x in required_file_names if x not in db_submitted_file_names]

        if s3_files is not None:
            s3_submitted_file_names = [x.get('name', '') for x in s3_files]
            missing_files = [x for x in missing_files if x not in s3_submitted_file_names]

        if len(missing_files) > 0:
            add_format_error(data, 'The following required files were missing: ' + ', '.join(missing_files))
        return

    if not files:
        add_format_error(data, 'No submitted answer for file upload.')
        return
