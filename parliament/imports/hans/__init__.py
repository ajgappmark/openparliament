# coding: utf8
"""Parse the Hansards of the House of Commons.

This module is organized like so:
__init__.py - utility functions, simple parse interface
common.py - infrastructure used in the parsers, i.e. regexes
current.py - parser for the Hansard format used from 2006 to the present
old.py - (fairly crufty) parser for the format used from 1994 to 2006

"""
import re, urllib, urllib2, datetime, sys, codecs
import pdb

from BeautifulSoup import BeautifulSoup, Comment, NavigableString
from django.db.models import Q
from django.db import transaction

from parliament.core.models import *
from parliament.hansards.models import Hansard, Statement, HansardCache
from parliament.core import parsetools
from parliament.imports.hans import current, old

def qp(id):
    """Utility quick-parse function. Takes a Hansard ID"""
    return parseAndSave(Hansard.objects.get(pk=id))
    
def soup(id):
    cache = loadHansard(Hansard.objects.get(pk=id))
    parser = _getParser(cache.hansard, cache.getHTML())
    return parser.soup
    
def _getParser(hansard, html):
    if hansard.session.start.year < 2006:
        return old.HansardParser1994(hansard, html)
    else:
        return current.HansardParser2009(hansard, html)

@transaction.commit_on_success
def parseAndSave(arg):
    if isinstance(arg, Hansard):
        cache = loadHansard(arg)
    elif isinstance(arg, HansardCache):
        cache = arg
    else:
        raise Exception("Invalid argument to parseAndSave")
        
    if Statement.objects.filter(hansard=cache.hansard).count() > 0:
        print "There are already Statements for %s." % cache.hansard
        print "Delete them? (y/n) ",
        yn = sys.stdin.readline().strip()
        if yn == 'y':
            for statement in Statement.objects.filter(hansard=cache.hansard):
                statement.delete()
        else:
            return False
    
    parser = _getParser(cache.hansard, cache.getHTML())
    
    statements = parser.parse()
    for statement in statements:
        #try:
        statement.save()
        statement.save_relationships()
        #except Exception, e:
        #    print "Error saving statement: %s %s" % (statement.sequence, statement.who)
        #    raise e 
    return True

def _getHansardNumber(page):
    title = re.search(r'<title>([^<]+)</title>', page).group(1)
    match = re.search(r'Number +(\d+\S*) ', parsetools.tameWhitespace(title)) # New format: Number 079
    if match:
        return re.sub('^0+', '', match.group(1))
    else:
        match = re.search(r'\((\d+\S*)\)', title) # Old format (079)
        if match:
            return re.sub('^0+', '', match.group(1))
        else:
            raise Exception("Couldn't parse number from Hansard title: %s" % title)
            
def loadHansard(hansard=None, url=None, session=None):
    if hansard:
        try:
            return HansardCache.objects.get(hansard=hansard)
        except HansardCache.DoesNotExist:
            if hansard.url:
                return loadHansard(url=hansard.url, session=hansard.session)
    elif url and session:
        normurl = parsetools.normalizeHansardURL(url)
        if normurl != url:
            print "WARNING: Normalized URL %s to %s" % (url, normurl)
        try:
            cached = HansardCache.objects.get(hansard__url=normurl)
            if cached.hansard.session != session:
                raise Exception("Found cached Hansard, but session doesn't match...")
            return cached
        except HansardCache.DoesNotExist:
            print "Downloading Hansard from %s" % normurl
            req = urllib2.Request(normurl)
            page = urllib2.urlopen(req).read()
            #try:
            number = _getHansardNumber(page)
            #except Exception, e:
            #    print e
            #    print "Couldn't get Hansard number for"
            #    print url
            #    print "Please enter: ",
            #    number = sys.stdin.readline().strip()
            try:
                hansard = Hansard.objects.get(session=session, number=number)
            except Hansard.DoesNotExist:
                hansard = Hansard(session=session, number=number, url=normurl)
                hansard.save()
            else:
                if hansard.url != normurl:
                    raise Exception("Hansard exists, with a different url: %s %s" % (normurl, hansard.url))
            cache = HansardCache(hansard=hansard)
            cache.saveHTML(page)
            cache.save()
            return cache
    else:
        raise Exception("Either url/session or hansard are required")