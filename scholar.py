import optparse
import os
import sys
import re

try:
    from urllib.request import HTTPCookieProcessor, Request, build_opener
    from urllib.parse import quote, unquote
    from http.cookiejar import MozillaCookieJar
except ImportError:
    from urllib2 import Request, build_opener, HTTPCookieProcessor
    from urllib import quote, unquote
    from cookielib import MozillaCookieJar

try:
    from bs4 import BeautifulSoup
except ImportError:
    try:
        from BeautifulSoup import BeautifulSoup
    except ImportError:
        print('We need BeautifulSoup, sorry...')
        sys.exit(1)

if sys.version_info[0] == 3:
    unicode = str 
    encode = lambda s: unicode(s)
else:
    def encode(s):
        if isinstance(s, basestring):
            return s.encode('utf-8') 
        else:
            return str(s)


class Error(Exception):
    """Base class for any Scholar error."""


class FormatError(Error):
    """A query argument or setting was formatted incorrectly."""


class QueryArgumentError(Error):
    """A query did not have a suitable set of arguments."""


class ScholarConf(object):
    """Helper class for global settings."""

    VERSION = '2.10'
    LOG_LEVEL = 1
    MAX_PAGE_RESULTS = 20 
    SCHOLAR_SITE = 'http://scholar.google.com'

    USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:27.0) Gecko/20100101 Firefox/27.0'

    COOKIE_JAR_FILE = None

class ScholarUtils(object):
    
    LOG_LEVELS = {'error': 1,
                  'warn':  2,
                  'info':  3,
                  'debug': 4}

    @staticmethod
    def ensure_int(arg, msg=None):
        try:
            return int(arg)
        except ValueError:
            raise FormatError(msg)

    @staticmethod
    def log(level, msg):
        if level not in ScholarUtils.LOG_LEVELS.keys():
            return
        if ScholarUtils.LOG_LEVELS[level] > ScholarConf.LOG_LEVEL:
            return
        sys.stderr.write('[%5s]  %s' % (level.upper(), msg + '\n'))
        sys.stderr.flush()


class ScholarArticle(object):
    def __init__(self):
        # The triplets for each keyword correspond to (1) the actual
        # value, (2) a user-suitable label for the item, and (3) an
        # ordering index:
        self.attrs = {
            'title':         [None, 'Title',          0],
            'url':           [None, 'URL',            1],
            'year':          [None, 'Year',           2],
            'num_citations': [0,    'Citations',      3],
            'num_versions':  [0,    'Versions',       4],
            'cluster_id':    [None, 'Cluster ID',     5],
            'url_pdf':       [None, 'PDF link',       6],
            'url_citations': [None, 'Citations list', 7],
            'url_versions':  [None, 'Versions list',  8],
            'url_citation':  [None, 'Citation link',  9],
            'excerpt':       [None, 'Excerpt',       10],
        }

        self.citation_data = None

    def __getitem__(self, key):
        if key in self.attrs:
            return self.attrs[key][0]
        return None

    def __len__(self):
        return len(self.attrs)

    def __setitem__(self, key, item):
        if key in self.attrs:
            self.attrs[key][0] = item
        else:
            self.attrs[key] = [item, key, len(self.attrs)]

    def __delitem__(self, key):
        if key in self.attrs:
            del self.attrs[key]

    def set_citation_data(self, citation_data):
        self.citation_data = citation_data

    def as_txt(self):
        items = sorted(list(self.attrs.values()), key=lambda item: item[2])
        max_label_len = max([len(str(item[1])) for item in items])
        fmt = '%%%ds %%s' % max_label_len
        res = []
        for item in items:
            if item[0] is not None:
                res.append(fmt % (item[1], item[0]))
        return '\n'.join(res)

    def as_csv(self, header=False, sep='|'):
        keys = [pair[0] for pair in \
                sorted([(key, val[2]) for key, val in list(self.attrs.items())],
                       key=lambda pair: pair[1])]
        res = []
        if header:
            res.append(sep.join(keys))
        res.append(sep.join([unicode(self.attrs[key][0]) for key in keys]))
        return '\n'.join(res)

    def as_citation(self):
        return self.citation_data or ''


class ScholarArticleParser(object):
    def __init__(self, site=None):
        self.soup = None
        self.article = None
        self.site = site or ScholarConf.SCHOLAR_SITE
        self.year_re = re.compile(r'\b(?:20|19)\d{2}\b')

    def handle_article(self, art):
       
    def handle_num_results(self, num_results):
       
    def parse(self, html):
        self.soup = BeautifulSoup(html)

        # This parses any global, non-itemized attributes from the page.
        self._parse_globals()

        # Now parse out listed articles:
        for div in self.soup.findAll(ScholarArticleParser._tag_results_checker):
            self._parse_article(div)
            self._clean_article()
            if self.article['title']:
                self.handle_article(self.article)

    def _clean_article(self):
        if self.article['title']:
            self.article['title'] = self.article['title'].strip()

    def _parse_globals(self):
        tag = self.soup.find(name='div', attrs={'id': 'gs_ab_md'})
        if tag is not None:
            raw_text = tag.findAll(text=True)
            # raw text is a list because the body contains <b> etc
            if raw_text is not None and len(raw_text) > 0:
                try:
                    num_results = raw_text[0].split()[1]
                    # num_results may now contain commas to separate
                    # thousands, strip:
                    num_results = num_results.replace(',', '')
                    num_results = int(num_results)
                    self.handle_num_results(num_results)
                except (IndexError, ValueError):
                    pass

    def _parse_article(self, div):
        self.article = ScholarArticle()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_rt') and \
                    tag.h3 and tag.h3.a:
                self.article['title'] = ''.join(tag.h3.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.h3.a['href'])
                if self.article['url'].endswith('.pdf'):
                    self.article['url_pdf'] = self.article['url']

            if tag.name == 'font':
                for tag2 in tag:
                    if not hasattr(tag2, 'name'):
                        continue
                    if tag2.name == 'span' and \
                       self._tag_has_class(tag2, 'gs_fl'):
                        self._parse_links(tag2)

    def _parse_links(self, span):
        for tag in span:
            if not hasattr(tag, 'name'):
                continue
            if tag.name != 'a' or tag.get('href') is None:
                continue

            if tag.get('href').startswith('/scholar?cites'):
                if hasattr(tag, 'string') and tag.string.startswith('Cited by'):
                    self.article['num_citations'] = \
                        self._as_int(tag.string.split()[-1])

                self.article['url_citations'] = \
                    self._strip_url_arg('num', self._path2url(tag.get('href')))

                args = self.article['url_citations'].split('?', 1)[1]
                for arg in args.split('&'):
                    if arg.startswith('cites='):
                        self.article['cluster_id'] = arg[6:]

            if tag.get('href').startswith('/scholar?cluster'):
                if hasattr(tag, 'string') and tag.string.startswith('All '):
                    self.article['num_versions'] = \
                        self._as_int(tag.string.split()[1])
                self.article['url_versions'] = \
                    self._strip_url_arg('num', self._path2url(tag.get('href')))

            if tag.getText().startswith('Import'):
                self.article['url_citation'] = self._path2url(tag.get('href'))


    @staticmethod
    def _tag_has_class(tag, klass):
        res = tag.get('class') or []
        if type(res) != list:
            res = res.split()
        return klass in res

    @staticmethod
    def _tag_results_checker(tag):
        return tag.name == 'div' \
            and ScholarArticleParser._tag_has_class(tag, 'gs_r')

    @staticmethod
    def _as_int(obj):
        try:
            return int(obj)
        except ValueError:
            return None

    def _path2url(self, path):
        if path.startswith('http://'):
            return path
        if not path.startswith('/'):
            path = '/' + path
        return self.site + path

    def _strip_url_arg(self, arg, url):
        parts = url.split('?', 1)
        if len(parts) != 2:
            return url
        res = []
        for part in parts[1].split('&'):
            if not part.startswith(arg + '='):
                res.append(part)
        return parts[0] + '?' + '&'.join(res)


class ScholarArticleParser120201(ScholarArticleParser):
    def _parse_article(self, div):
        self.article = ScholarArticle()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'h3' and self._tag_has_class(tag, 'gs_rt') and tag.a:
                self.article['title'] = ''.join(tag.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.a['href'])
                if self.article['url'].endswith('.pdf'):
                    self.article['url_pdf'] = self.article['url']

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_a'):
                year = self.year_re.findall(tag.text)
                self.article['year'] = year[0] if len(year) > 0 else None

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_fl'):
                self._parse_links(tag)


class ScholarArticleParser120726(ScholarArticleParser):
    def _parse_article(self, div):
        self.article = ScholarArticle()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue
            if str(tag).lower().find('.pdf'):
                if tag.find('div', {'class': 'gs_ttss'}):
                    self._parse_links(tag.find('div', {'class': 'gs_ttss'}))

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_ri'):
                try:
                    atag = tag.h3.a
                    self.article['title'] = ''.join(atag.findAll(text=True))
                    self.article['url'] = self._path2url(atag['href'])
                    if self.article['url'].endswith('.pdf'):
                        self.article['url_pdf'] = self.article['url']
                except:
                    for span in tag.h3.findAll(name='span'):
                        span.clear()
                    self.article['title'] = ''.join(tag.h3.findAll(text=True))

                if tag.find('div', {'class': 'gs_a'}):
                    year = self.year_re.findall(tag.find('div', {'class': 'gs_a'}).text)
                    self.article['year'] = year[0] if len(year) > 0 else None

                if tag.find('div', {'class': 'gs_fl'}):
                    self._parse_links(tag.find('div', {'class': 'gs_fl'}))

                if tag.find('div', {'class': 'gs_rs'}):
                    raw_text = tag.find('div', {'class': 'gs_rs'}).findAll(text=True)
                    if len(raw_text) > 0:
                        raw_text = ''.join(raw_text)
                        raw_text = raw_text.replace('\n', '')
                        self.article['excerpt'] = raw_text


class ScholarQuery(object):
    def __init__(self):
        self.url = None
    self.num_results = ScholarConf.MAX_PAGE_RESULTS
        self.attrs = {}

    def set_num_page_results(self, num_page_results):
        msg = 'maximum number of results on page must be numeric'
        self.num_results = ScholarUtils.ensure_int(num_page_results, msg)

    def get_url(self):
        return None

    def _add_attribute_type(self, key, label, default_value=None):
        if len(self.attrs) == 0:
            self.attrs[key] = [default_value, label, 0]
            return
        idx = max([item[2] for item in self.attrs.values()]) + 1
        self.attrs[key] = [default_value, label, idx]

    def __getitem__(self, key):
        if key in self.attrs:
            return self.attrs[key][0]
        return None

    def __setitem__(self, key, item):
        if key in self.attrs:
            self.attrs[key][0] = item

    def _parenthesize_phrases(self, query):
        if query.find(',') < 0:
            return query
        phrases = []
        for phrase in query.split(','):
            phrase = phrase.strip()
            if phrase.find(' ') > 0:
                phrase = '"' + phrase + '"'
            phrases.append(phrase)
        return ' '.join(phrases)


class ClusterScholarQuery(ScholarQuery):
    SCHOLAR_CLUSTER_URL = ScholarConf.SCHOLAR_SITE + '/scholar?' \
        + 'cluster=%(cluster)s' \
        + '&num=%(num)s'

    def __init__(self, cluster=None):
        ScholarQuery.__init__(self)
        self._add_attribute_type('num_results', 'Results', 0)
        self.cluster = None
        self.set_cluster(cluster)

    def set_cluster(self, cluster):
        msg = 'cluster ID must be numeric'
        self.cluster = ScholarUtils.ensure_int(cluster, msg)

    def get_url(self):
        if self.cluster is None:
            raise QueryArgumentError('cluster query needs cluster ID')

        urlargs = {'cluster': self.cluster,
                   'num': self.num_results or ScholarConf.MAX_PAGE_RESULTS}

        for key, val in urlargs.items():
            urlargs[key] = quote(encode(val))

        return self.SCHOLAR_CLUSTER_URL % urlargs


class SearchScholarQuery(ScholarQuery):
    SCHOLAR_QUERY_URL = ScholarConf.SCHOLAR_SITE + '/scholar?' \
        + 'as_q=%(words)s' \
        + '&as_epq=%(phrase)s' \
        + '&as_oq=%(words_some)s' \
        + '&as_eq=%(words_none)s' \
        + '&as_occt=%(scope)s' \
        + '&as_sauthors=%(authors)s' \
        + '&as_publication=%(pub)s' \
        + '&as_ylo=%(ylo)s' \
        + '&as_yhi=%(yhi)s' \
        + '&as_sdt=%(patents)s%%2C5' \
        + '&as_vis=%(citations)s' \
        + '&btnG=&hl=en' \
        + '&num=%(num)s'

    def __init__(self):
        ScholarQuery.__init__(self)
        self._add_attribute_type('num_results', 'Results', 0)
        self.words = None # The default search behavior
        self.words_some = None # At least one of those words
        self.words_none = None # None of these words
        self.phrase = None
        self.scope_title = False # If True, search in title only
        self.author = None 
        self.pub = None
        self.timeframe = [None, None]
        self.include_patents = True
        self.include_citations = True

    def set_words(self, words):
        self.words = words

    def set_words_some(self, words):
        self.words_some = words

    def set_words_none(self, words):
        self.words_none = words

    def set_phrase(self, phrase):
        self.phrase = phrase

    def set_scope(self, title_only):
        self.scope_title = title_only

    def set_author(self, author):
        self.author = author

    def set_pub(self, pub):
        self.pub = pub

    def set_timeframe(self, start=None, end=None):
        if start:
            start = ScholarUtils.ensure_int(start)
        if end:
            end = ScholarUtils.ensure_int(end)
        self.timeframe = [start, end]

    def set_include_citations(self, yesorno):
        self.include_citations = yesorno

    def set_include_patents(self, yesorno):
        self.include_patents = yesorno

    def get_url(self):
        if self.words is None and self.words_some is None \
           and self.words_none is None and self.phrase is None \
           and self.author is None and self.pub is None \
           and self.timeframe[0] is None and self.timeframe[1] is None:
            raise QueryArgumentError('search query needs more parameters')

        words_some = None
        words_none = None

        if self.words_some:
            words_some = self._parenthesize_phrases(self.words_some)
        if self.words_none:
            words_none = self._parenthesize_phrases(self.words_none)

        urlargs = {'words': self.words or '',
                   'words_some': words_some or '',
                   'words_none': words_none or '',
                   'phrase': self.phrase or '',
                   'scope': 'title' if self.scope_title else 'any',
                   'authors': self.author or '',
                   'pub': self.pub or '',
                   'ylo': self.timeframe[0] or '',
                   'yhi': self.timeframe[1] or '',
                   'patents': '0' if self.include_patents else '1',
                   'citations': '0' if self.include_citations else '1',
                   'num': self.num_results or ScholarConf.MAX_PAGE_RESULTS}

        for key, val in urlargs.items():
            urlargs[key] = quote(encode(val))

        return self.SCHOLAR_QUERY_URL % urlargs


class ScholarSettings(object):

    CITFORM_NONE = 0
    CITFORM_REFWORKS = 1
    CITFORM_REFMAN = 2
    CITFORM_ENDNOTE = 3
    CITFORM_BIBTEX = 4

    def __init__(self):
        self.citform = 0 # Citation format, default none
        self.per_page_results = ScholarConf.MAX_PAGE_RESULTS
        self._is_configured = False

    def set_citation_format(self, citform):
        citform = ScholarUtils.ensure_int(citform)
        if citform < 0 or citform > self.CITFORM_BIBTEX:
            raise FormatError('citation format invalid, is "%s"' \
                              % citform)
        self.citform = citform
        self._is_configured = True

    def set_per_page_results(self, per_page_results):
        msg = 'page results must be integer'
        self.per_page_results = ScholarUtils.ensure_int(per_page_results, msg)
        self.per_page_results = min(self.per_page_results,
                                    ScholarConf.MAX_PAGE_RESULTS)
        self._is_configured = True

    def is_configured(self):
        return self._is_configured


class ScholarQuerier(object):

    
    GET_SETTINGS_URL = ScholarConf.SCHOLAR_SITE + '/scholar_settings?' \
        + 'sciifh=1&hl=en&as_sdt=0,5'

    SET_SETTINGS_URL = ScholarConf.SCHOLAR_SITE + '/scholar_setprefs?' \
        + 'q=' \
        + '&scisig=%(scisig)s' \
        + '&inststart=0' \
        + '&as_sdt=1,5' \
        + '&as_sdtp=' \
        + '&num=%(num)s' \
        + '&scis=%(scis)s' \
        + '%(scisf)s' \
        + '&hl=en&lang=all&instq=&inst=569367360547434339&save='

   
    class Parser(ScholarArticleParser120726):
        def __init__(self, querier):
            ScholarArticleParser120726.__init__(self)
            self.querier = querier

        def handle_num_results(self, num_results):
            if self.querier is not None and self.querier.query is not None:
                self.querier.query['num_results'] = num_results

        def handle_article(self, art):
            self.querier.add_article(art)

    def __init__(self):
        self.articles = []
        self.query = None
        self.cjar = MozillaCookieJar()

        if ScholarConf.COOKIE_JAR_FILE and \
           os.path.exists(ScholarConf.COOKIE_JAR_FILE):
            try:
                self.cjar.load(ScholarConf.COOKIE_JAR_FILE,
                               ignore_discard=True)
                ScholarUtils.log('info', 'loaded cookies file')
            except Exception as msg:
                ScholarUtils.log('warn', 'could not load cookies file: %s' % msg)
                self.cjar = MozillaCookieJar() 

        self.opener = build_opener(HTTPCookieProcessor(self.cjar))
        self.settings = None

    def apply_settings(self, settings):
        if settings is None or not settings.is_configured():
            return True

        self.settings = settings

        html = self._get_http_response(url=self.GET_SETTINGS_URL,
                                       log_msg='dump of settings form HTML',
                                       err_msg='requesting settings failed')
        if html is None:
            return False

        soup = BeautifulSoup(html)

        tag = soup.find(name='form', attrs={'id': 'gs_settings_form'})
        if tag is None:
            ScholarUtils.log('info', 'parsing settings failed: no form')
            return False

        tag = tag.find('input', attrs={'type':'hidden', 'name':'scisig'})
        if tag is None:
            ScholarUtils.log('info', 'parsing settings failed: scisig')
            return False

        urlargs = {'scisig': tag['value'],
                   'num': settings.per_page_results,
                   'scis': 'no',
                   'scisf': ''}

        if settings.citform != 0:
            urlargs['scis'] = 'yes'
            urlargs['scisf'] = '&scisf=%d' % settings.citform

        html = self._get_http_response(url=self.SET_SETTINGS_URL % urlargs,
                                       log_msg='dump of settings result HTML',
                                       err_msg='applying setttings failed')
        if html is None:
            return False

        ScholarUtils.log('info', 'settings applied')
        return True

    def send_query(self, query):
         self.clear_articles()
        self.query = query

        html = self._get_http_response(url=query.get_url(),
                                       log_msg='dump of query response HTML',
                                       err_msg='results retrieval failed')
        if html is None:
            return

        self.parse(html)

    def get_citation_data(self, article):
        if article['url_citation'] is None:
            return False
        if article.citation_data is not None:
            return True

        ScholarUtils.log('info', 'retrieving citation export data')
        data = self._get_http_response(url=article['url_citation'],
                                       log_msg='citation data response',
                                       err_msg='requesting citation data failed')
        if data is None:
            return False

        article.set_citation_data(data)
        return True

    def parse(self, html):
        parser = self.Parser(self)
        parser.parse(html)

    def add_article(self, art):
        self.get_citation_data(art)
        self.articles.append(art)

    def clear_articles(self):
        self.articles = []

    def save_cookies(self):
        if ScholarConf.COOKIE_JAR_FILE is None:
            return False
        try:
            self.cjar.save(ScholarConf.COOKIE_JAR_FILE,
                           ignore_discard=True)
            ScholarUtils.log('info', 'saved cookies file')
            return True
        except Exception as msg:
            ScholarUtils.log('warn', 'could not save cookies file: %s' % msg)
            return False

    def _get_http_response(self, url, log_msg=None, err_msg=None):
        if log_msg is None:
            log_msg = 'HTTP response data follow'
        if err_msg is None:
            err_msg = 'request failed'
        try:
            ScholarUtils.log('info', 'requesting %s' % unquote(url))

            req = Request(url=url, headers={'User-Agent': ScholarConf.USER_AGENT})
            hdl = self.opener.open(req)
            html = hdl.read()

            ScholarUtils.log('debug', log_msg)
            ScholarUtils.log('debug', '>>>>' + '-'*68)
            ScholarUtils.log('debug', 'url: %s' % hdl.geturl())
            ScholarUtils.log('debug', 'result: %s' % hdl.getcode())
            ScholarUtils.log('debug', 'headers:\n' + str(hdl.info()))
            ScholarUtils.log('debug', 'data:\n' + html.decode('utf-8')) # For Python 3
            ScholarUtils.log('debug', '<<<<' + '-'*68)

            return html
        except Exception as err:
            ScholarUtils.log('info', err_msg + ': %s' % err)
            return None


def txt(querier, with_globals):
    if with_globals:
        max_label_len = 0
        if len(querier.articles) > 0:
            items = sorted(list(querier.articles[0].attrs.values()),
                           key=lambda item: item[2])
            max_label_len = max([len(str(item[1])) for item in items])

        items = sorted(list(querier.query.attrs.values()), key=lambda item: item[2])
        max_label_len = max([len(str(item[1])) for item in items] + [max_label_len])
        fmt = '[G] %%%ds %%s' % max(0, max_label_len-4)
        for item in items:
            if item[0] is not None:
                print(fmt % (item[1], item[0]))
        if len(items) > 0:
            print

    articles = querier.articles
    for art in articles:
        print(encode(art.as_txt()) + '\n')

def csv(querier, header=False, sep='|'):
    articles = querier.articles
    for art in articles:
        result = art.as_csv(header=header, sep=sep)
        print(encode(result))
        header = False

def citation_export(querier):
    articles = querier.articles
    for art in articles:
        print(art.as_citation() + '\n')


def main():
    usage = 
    fmt = optparse.IndentedHelpFormatter(max_help_position=50, width=100)
    parser = optparse.OptionParser(usage=usage, formatter=fmt)
    group = optparse.OptionGroup(parser, 'Query arguments',
                                 'These options define search query arguments and parameters.')
    group.add_option('-a', '--author', metavar='AUTHORS', default=None,
                     help='Author name(s)')
    group.add_option('-A', '--all', metavar='WORDS', default=None, dest='allw',
                     help='Results must contain all of these words')
    group.add_option('-s', '--some', metavar='WORDS', default=None,
                     help='Results must contain at least one of these words. Pass arguments in form -s "foo bar baz" for simple words, and -s "a phrase, another phrase" for phrases')
    group.add_option('-n', '--none', metavar='WORDS', default=None,
                     help='Results must contain none of these words. See -s|--some re. formatting')
    group.add_option('-p', '--phrase', metavar='PHRASE', default=None,
                     help='Results must contain exact phrase')
    group.add_option('-t', '--title-only', action='store_true', default=False,
                     help='Search title only')
    group.add_option('-P', '--pub', metavar='PUBLICATIONS', default=None,
                     help='Results must have appeared in this publication')
    group.add_option('--after', metavar='YEAR', default=None,
                     help='Results must have appeared in or after given year')
    group.add_option('--before', metavar='YEAR', default=None,
                     help='Results must have appeared in or before given year')
    group.add_option('--no-patents', action='store_true', default=False,
                     help='Do not include patents in results')
    group.add_option('--no-citations', action='store_true', default=False,
                     help='Do not include citations in results')
    group.add_option('-C', '--cluster-id', metavar='CLUSTER_ID', default=None,
                     help='Do not search, just use articles in given cluster ID')
    group.add_option('-c', '--count', type='int', default=None,
                     help='Maximum number of results')
    parser.add_option_group(group)

    group = optparse.OptionGroup(parser, 'Output format',
                                 'These options control the appearance of the results.')
    group.add_option('--txt', action='store_true',
                     help='Print article data in text format (default)')
    group.add_option('--txt-globals', action='store_true',
                     help='Like --txt, but first print global results too')
    group.add_option('--csv', action='store_true',
                     help='Print article data in CSV form (separator is "|")')
    group.add_option('--csv-header', action='store_true',
                     help='Like --csv, but print header with column names')
    group.add_option('--citation', metavar='FORMAT', default=None,
                     help='Print article details in standard citation format. Argument Must be one of "bt" (BibTeX), "en" (EndNote), "rm" (RefMan), or "rw" (RefWorks).')
    parser.add_option_group(group)

    group = optparse.OptionGroup(parser, 'Miscellaneous')
    group.add_option('--cookie-file', metavar='FILE', default=None,
                     help='File to use for cookie storage. If given, will read any existing cookies if found at startup, and save resulting cookies in the end.')
    group.add_option('-d', '--debug', action='count', default=0,
                     help='Enable verbose logging to stderr. Repeated options increase detail of debug output.')
    group.add_option('-v', '--version', action='store_true', default=False,
                     help='Show version information')
    parser.add_option_group(group)

    options, _ = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return 1

    if options.debug > 0:
        options.debug = min(options.debug, ScholarUtils.LOG_LEVELS['debug'])
        ScholarConf.LOG_LEVEL = options.debug
        ScholarUtils.log('info', 'using log level %d' % ScholarConf.LOG_LEVEL)

    if options.version:
        print('This is scholar.py %s.' % ScholarConf.VERSION)
        return 0

    if options.cookie_file:
        ScholarConf.COOKIE_JAR_FILE = options.cookie_file

    if options.cluster_id is not None:
        if options.author or options.allw or options.some or options.none \
           or options.phrase or options.title_only or options.pub \
           or options.after or options.before:
            print('Cluster ID queries do not allow additional search arguments.')
            return 1

    querier = ScholarQuerier()
    settings = ScholarSettings()

    if options.citation == 'bt':
        settings.set_citation_format(ScholarSettings.CITFORM_BIBTEX)
    elif options.citation == 'en':
        settings.set_citation_format(ScholarSettings.CITFORM_ENDNOTE)
    elif options.citation == 'rm':
        settings.set_citation_format(ScholarSettings.CITFORM_REFMAN)
    elif options.citation == 'rw':
        settings.set_citation_format(ScholarSettings.CITFORM_REFWORKS)
    elif options.citation is not None:
        print('Invalid citation link format, must be one of "bt", "en", "rm", or "rw".')
        return 1

    querier.apply_settings(settings)

    if options.cluster_id:
        query = ClusterScholarQuery(cluster=options.cluster_id)
    else:
        query = SearchScholarQuery()
        if options.author:
            query.set_author(options.author)
        if options.allw:
            query.set_words(options.allw)
        if options.some:
            query.set_words_some(options.some)
        if options.none:
            query.set_words_none(options.none)
        if options.phrase:
            query.set_phrase(options.phrase)
        if options.title_only:
            query.set_scope(True)
        if options.pub:
            query.set_pub(options.pub)
        if options.after or options.before:
            query.set_timeframe(options.after, options.before)
        if options.no_patents:
            query.set_include_patents(False)
        if options.no_citations:
            query.set_include_citations(False)

    if options.count is not None:
        options.count = min(options.count, ScholarConf.MAX_PAGE_RESULTS)
        query.set_num_page_results(options.count)

    querier.send_query(query)

    if options.csv:
        csv(querier)
    elif options.csv_header:
        csv(querier, header=True)
    elif options.citation is not None:
        citation_export(querier)
    else:
        txt(querier, with_globals=options.txt_globals)

    if options.cookie_file:
        querier.save_cookies()

    return 0

if __name__ == "__main__":
    sys.exit(main())
