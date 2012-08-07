import xml.etree.ElementTree as et
from flask import abort
import osmapi
import parser
import urllib2
import yaml
from features import Feature
import inflect
import elements

p = inflect.engine()

def populate_features_in_yaml(database, yamlfile):
    with open(yamlfile) as fd:
        data = fd.read()
        yamldata = yaml.load(data)
        for item in yamldata:
            feature = elements.dict2feature(item)
            database.addFeature(feature)

def get_feature_or_404(element_id):
    try:
        o_type, oid = element_id.split(':')
    except ValueError:
        abort(404, 'Element identifier not valid')
    api = { 'node': osmapi.getNode,
            'way': osmapi.getWay,
            'relation': osmapi.getRelation}
    parsers = { 'node': parser.parseNode,
                'way': parser.parseWay,
                'relation': parser.parseRelation}
    try:
        data = api[o_type](oid)
        xml = et.XML(data)
        root = xml.find(o_type)
        return parsers[o_type](root)
    except urllib2.HTTPError, e:
        abort(404, e)
    except urllib2.URLError, e:
        abort(501, e)
    except KeyError, e:
        abort(404, "Element type not valid")

def get_changeset_or_404(changesetid):
    # A changeset actually needs information from both the changeset
    # and from the osmchange
    try:
        changeset_raw = osmapi.getChangeset(changesetid)
        xml = et.XML(changeset_raw)
        changeset = parser.parseChangeset(xml.find('changeset'))
        change_raw = osmapi.getChange(changesetid)
        xml = et.XML(change_raw)
        change = parser.parseChange(xml)
        changeset['actions'] = change
        return changeset
    except urllib2.HTTPError, e:
        abort(404, e)
    except urllib2.URLError, e:
        abort(501, e)

def get_user(changeset):
    if changeset.has_key('user'):
        return changeset['user']
    else:
        return 'User %s' % (str(changeset['uid']))

def sort_by_num_features(coll):
    def sort_num_features(a, b):
        return len(b[1]) - len(a[1])
    return sorted(coll, cmp=sort_num_features)

def feature_grouper(coll):
    """Takes in a collection of elements and features and groups them
    by feature in the supplied order
    """
    # This function isn't very efficient and should likely be
    # rewritten
    grouped = []
    while coll:
        feature = coll[0][1][0]
        eles = [f[0] for f in coll if feature in f[1]]
        grouped.append( (eles, feature) )
        coll = [f for f in coll if feature not in f[1]]
    return grouped

def sort_grouped(coll):
    """Sort a grouped collection (from feature_grouper)"""
    def sort_num_elements(a, b):
        return len(b[0]) - len(a[0])
    return sorted(coll, cmp=sort_num_elements)

def grouped_to_english(coll):
    """Take a grouped collection (from feature_grouper) and return it
    as a human readable string
    """
    l = []
    for elements, feature in coll:
        if len(elements) > 1:
            l.append("%s %s" % (p.number_to_words(len(elements)),
                                feature.plural))
        else:            
            l.append(display_name(elements[0], feature))
    return p.join(l)

def sort_elements(coll):
    """Take a collection of elements and sort them in a way that's
    suitable for uniquing, and reverse referencing
    """
    relations = [e for e in coll if e['type'] == 'relation']
    ways = [e for e in coll if e['type'] == 'way']
    nodes = [e for e in coll if e['type'] == 'node']
    l = []
    def sortfn(a, b):
        r = a['id'] - b['id']
        if r == 0:
            return a['version'] - b['version']
        else:
            return r
    l.extend(sorted(nodes, cmp=sortfn))
    l.extend(sorted(ways, cmp=sortfn))
    l.extend(sorted(relations, cmp=sortfn))
    return l

def unique_elements(coll):
    """Takes a sorted collection of elements. Returns those elements
    uniqued by version. Also removes dupes.
    """
    i = 0
    while i <= len(coll):
        ele = coll[i]
        next_ele = coll[i + 1]
        if ( ele['type'] == next_ele['type'] and
             ele['id'] == next_ele['id'] and
             ele['version'] <= next_ele['version']):
            coll.pop(i)
        else:
            i += 1
        
def remove_unnecessary_items(coll):
    """Takes a collection of elements and removes those which are
    tagless but have either a way reference or a relation reference
    """
    l = []
    for ele in coll:
        if not ele['tags']:
            if ele.has_key('_ways') or ele.has_key('_relations'):
                continue
        else:
            l.append(ele)
    return l

    """Takes a collection of elements and removes tagless objects
    belonging to another object
    """
    # This is not the most network efficient mechanism to get this,
    # but it'll do for now
    coll_idx = {}
    for ele in coll:
        if ele['tags']:
            continue
        # This element is tagless
        if ele['type'] == 'node':
            raw_ways = osmapi.getWaysforNode(ele['id'])
            root = xml_find('osm')
            ways = [way for way in parseWay(root.findall('way'))]
        relations = [rel for rel in
                     parseRelation(root.findall('relation'))]
        
        if not ways or not relations
                    # This is significant
                    l.append(ele)
                for way in ways:
                    # We need to be sure that this way isn't already accounted for (because we're adding them
                for relation in relations:
                    l.append(relation)
                

def add_local_way_references(coll):
    """Takes a collection of elements and adds way callbacks to the nodes"""
    # This isn't the most efficient way to do this
    nodes = [ele for ele in coll if ele['type'] == 'node']
    ways = [ele for ele in coll if ele['type'] == 'way']
    for way in ways:
        nd = way['nd']
        for node in [node for node in nodes if node['id'] in nd]:
            if node.has_key('_ways'):
                node['_ways'].append(way['id'])
            else:
                node['_ways'] = [way['id']]

def add_local_relation_references(coll):
    # Same here about inefficiency
    relations = [ele for ele in coll if ele['type'] == 'relation']
    for rel in relations:
        members = [ (i['type'], i['ref']) for i in rel['members']]
        for member in members:
            type = ele['type']
            id = ele['id']
            # We'll use a list comprehension here even though it
            # should only return a single element
            for ele in [e in coll if e['type'] == type and e['id'] == id]:
                if ele.has_key('_relations'):
                    ele['_relations'].append(rel['id'])
                else:
                    ele['_relations'] = [rel['id']]

def add_remote_ways(coll):
    """Takes a collection of elements and adds way references for
    nodes if they don't have tags, or existing ways
    """
    nodes = [ele for ele in coll if (ele['type'] == 'node'
                                     and not ele['tags']
                                     and not ele.has_key('_ways'))]
    for node in nodes:
        # We don't care about duplicate ways for now. We'll de-dup later
        data = getWaysforNode(node['id'])
        xml = et.XML(data)
        root = xml.find('osm')
        ways = [way for way in parser.parseWay(root.findall('way'))]
        for way in ways:
            coll.append(way)
            if node.has_key('_ways'):
                node['_ways'].append(way['id'])
            else:
                node['_ways'] = [way['id']]

def add_remote_relations(coll):
    elements = [ele for ele in coll if (not ele['tags']
                                        and not ele.has_key('_relations'))]
    for ele in elements:
        data = getRelationsforElement(ele['type'], ele['id'])
        xml = et.XML(data)
        root = xml.find('osm')
        relations = [rel for rel in parser.parseRelation(root.findall('relation'))]
        for rel in relations:
            coll.append(rel)
            if ele.has_key('_relations'):
                ele['_relations'].append(rel['id'])
            else:
                ele['_relations'] = [rel['id']]