#!/usr/bin/env python
#
# (C) Copyright 2012- ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation nor
# does it submit to any jurisdiction.
#


import datetime
from collections import defaultdict
from copy import copy, deepcopy
from functools import cmp_to_key

from dateutil.parser import parse as parse_dates


class Interval(object):
    def __init__(self, start, end):
        self.start = start
        self.end = end
        if isinstance(start, datetime.datetime):
            self.one = datetime.timedelta(hours=1)
        else:
            self.one = datetime.timedelta(days=1)
        assert start <= end

    def split(self, dates):
        result = []

        bounds = set(dates)

        bounds.remove(self.start)
        bounds.remove(self.end)

        s = self.start
        e = self.end
        for b in sorted(bounds):
            if b >= s and b <= e:
                result.append(self.__class__(s, b))
                s = b + self.one

        result.append(self.__class__(s, e))
        return result

    def overlaps(self, other):
        s1, e1 = self.start, self.end + self.one
        s2, e2 = other.start, other.end + self.one
        s = max(s1, s2)
        e = min(e1, e2)
        if s <= e:
            return self.__class__(min(s1, s2), max(e1, e2) - self.one)
        else:
            return None

    @classmethod
    def join(cls, intervals):
        result = list(intervals)

        more = True
        while more:
            more = False

            for i in range(0, len(result)):
                if result[i] is not None:
                    for j in range(0, len(result)):
                        if result[j] is not None:
                            if i != j:
                                if result[i].overlaps(result[j]):
                                    result[i] = result[i].overlaps(result[j])
                                    result[j] = None
                                    more = True

        return [r for r in result if r is not None]

    def __repr__(self):
        if isinstance(self.start, datetime.date):
            return "%s/%s" % (
                self.start.strftime("%Y-%m-%d"),
                self.end.strftime("%Y-%m-%d"),
            )
        return "%s/%s" % (self.start.isoformat(), self.end.isoformat())

    def __lt__(self, other):
        return (self.start, self.end) < (other.start, other.end)

    def __le__(self, other):
        return (self.start, self.end) <= (other.start, other.end)

    def __gt__(self, other):
        return (self.start, self.end) > (other.start, other.end)

    def __ge__(self, other):
        return (self.start, self.end) >= (other.start, other.end)

    def __eq__(self, other):
        return (self.start, self.end) == (other.start, other.end)

    def __ne__(self, other):
        return (self.start, self.end) != (other.start, other.end)

    def __hash__(self):
        return hash((self.start, self.end))


def _cleanup(x):

    if isinstance(x, (list, tuple)):
        return [_cleanup(a) for a in x]

    if isinstance(x, dict):
        r = {}
        for k, v in x.items():
            r[_cleanup(k)] = _cleanup(v)
        return r

    if isinstance(x, (str, int, float)):
        return x

    return str(repr(x))


def _as_tuple(t):
    if isinstance(t, tuple):
        return t
    if isinstance(t, list) and len(t) == 1:
        return _as_tuple(t[0])
    if isinstance(t, (list, set)):
        return tuple(t)
    return (t,)


def _as_interval(interval):
    if not isinstance(interval, (list, tuple)):
        interval = [interval]
    result = []
    for t in interval:
        start, end = t.split("/")
        start = parse_dates(start)
        end = parse_dates(end)
        result.append(Interval(start, end))
    return result


class Tree:
    def __init__(self, values=None):
        self._values = {} if values is None else values
        self._children = []
        self._unique_values = None
        self._flatten = None

    def _add_child(self, child):
        self._children.append(child)

    def _set_value(self, name, value):
        self._values[name] = value

    def _join_intervals(self, name):
        for c in self._children:
            c._join_intervals(name)

        if name in self._values:
            self._values[name] = Interval.join(self._values[name])

    @property
    def unique_values(self):
        if self._unique_values is None:
            u = self._unique_values = {}

            for r in self.flatten:
                for k, v in r.items():
                    u.setdefault(k, set())
                    for x in v:
                        u[k].add(x)

        return self._unique_values

    @property
    def flatten(self):
        if self._flatten is None:
            self._flatten = list(self._flatten_tree())
        return self._flatten

    def _flatten_tree(self):
        if not self._children:
            yield self._values
        else:
            for c in self._children:
                for t in c._flatten_tree():
                    r = dict(**self._values)
                    r.update(t)
                    yield r

    def to_list(self):
        result = []
        for r in _cleanup(self.flatten):
            s = {}
            for k, v in sorted(r.items()):
                s[k] = sorted(v)
            result.append(s)

        return sorted(result, key=lambda a: sorted(a.items()))

    def _repr_html_(self):
        html = [repr(self._values)]
        html.append("<ul>")
        for c in self._children:
            html.append(c._repr_html_())
        html.append("</ul>")

        return "".join(html)

    def select(self, **kwargs):
        request = {}
        for k, v in kwargs.items():
            request[k] = _as_tuple(v)
        return self._select(request)

    def _select(self, request):
        ok, matches = self._match(request)
        if not ok:
            return None

        r = dict(**self._values)
        for name, values in [(n, v) for (n, v) in matches.items() if n in self._values]:
            r[name] = _as_tuple(values)
        result = Tree(r)

        if not self._children:
            return result

        count = 0
        for c in self._children:
            s = c._select(request)
            if s is not None:
                count += 1
                result._add_child(s)

        if count == 0:
            return None

        return result

    def _match(self, request):
        matches = {}
        for name, values in [(n, v) for (n, v) in request.items() if n in self._values]:
            common = set(values).intersection(set(self._values[name]))
            if len(common) == 0:
                return False, None

            if False:  # If we want an exact match
                if len(common) != len(values):
                    return False, None

            matches[name] = common

        return True, matches


class Compressor:

    _value2code = {}
    _code2value = []

    def encode_requests(self, req):
        if not isinstance(req, list):
            req = [req]

        for r in req:
            for k, v in r.items():
                if not isinstance(v, (list, set, tuple)):
                    r[k] = [v]

        for name in self.all_keys(req):
            p = self.all_values(req, name)
            for r, l in zip(req, self.compress_lists(p)):
                r[name] = l

    def encode(self, x):

        x = _as_tuple(x)

        y = self._value2code.get(x)
        if y is not None:
            return y

        c = len(self._code2value)
        self._value2code[x] = c
        self._code2value.append(x)
        return c

    def decode(self, x):
        return self._code2value[x]

    def compress_lists(self, lst):
        """
        Find common groups in list and transform them in element

        => [ [1, 2, 3, 4, 5], [2, 3, 8, 9, 4], [3, 4, 5, 9, 2, 8, 1] ]
        <= [{(1, 5), (2, 3, 4)}, {(8, 9), (2, 3, 4)}, {(8, 9), (1, 5), (2, 3, 4)}]


        """

        assert isinstance(lst, list)
        for x in lst:
            assert isinstance(x, list)

        lst = [set(x) for x in lst]

        r = list([set() for x in lst])

        more = True
        while more:
            more = False
            for i in range(0, len(lst)):
                if len(lst[i]):
                    g = set(lst[i]).intersection(*lst[i + 1 :])
                    if len(g):
                        for i, s in enumerate(lst):

                            if len(s) and g <= s:
                                r[i].add(self.encode(g))
                                lst[i] = s - g
                                more = True
                    else:
                        r[i].add(self.encode(lst[i]))
                        lst[i] = []

        return [tuple(x) for x in r]

    def all_keys(self, requests):
        return set().union(*[r.keys() for r in requests])

    def all_values(self, requests, name):
        return [r.get(name, ["-"]) for r in requests]

    def decode_tree(self, req):
        for r in req:
            if "_kids" in r:
                self.decode_tree(r["_kids"])

            for k, v in r.items():
                if k != "_kids":
                    newv = []
                    for x in v:
                        newv.extend(self.decode(x))
                    r[k] = newv


class Column(object):
    """Just what is says on the tin, a column of values."""

    def __init__(self, title, values):
        self.title = title
        self.values = values
        self.prio = 0
        self.diff = -1

    def __lt__(self, other):
        return (self.prio, self.diff, self.title) < (
            other.prio,
            other.diff,
            other.title,
        )

    def value(self, i):
        return self.values[i]

    def set_value(self, i, v):
        self.values[i] = v

    def compute_differences(self, idx):
        """
        Number of unique values in this column for the requested
        row indexes.

        @param idx list of row indexes
        """
        x = [self.values[i] for i in idx]
        try:
            self.diff = len(set(x))
        except Exception:
            print(type(x))
            print(x[:10])
            raise

    def __repr__(self):
        return "Column(%s,%s,%s,%s)" % (self.title, self.values, self.prio, self.diff)


class Table(object):
    def __init__(self, other=None, a=None, b=None):

        self.tree = Tree()

        if other is not None:
            self.depth = other.depth + 1
            self.cols = copy(other.cols)
            self.colidx = copy(other.colidx)
            self.rowidx = other.rowidx[a:b]
        else:
            self.depth = 0
            self.cols = []
            self.colidx = []
            self.rowidx = []

    def get_elem(self, c, r):
        return self.cols[self.colidx[c]].value(self.rowidx[r])

    def set_elem(self, c, r, v):
        return self.cols[self.colidx[c]].set_value(self.rowidx[r], v)

    def __repr__(self):
        return repr(
            [[self.cols[col].value(row) for row in self.rowidx] for col in self.colidx]
        )

    def column(self, s, col):
        self.cols.append(Column(s, col))
        self.colidx.append(len(self.colidx))

        if len(col) > len(self.rowidx):
            self.rowidx = [i for i in range(0, len(col))]

    def one_less(self, r, n):
        return [self.get_elem(i, r) for i in range(len(self.colidx)) if i != n]

    def factorise1(self):
        self.pop_singles()
        self.sort_rows()

        for i in range(0, len(self.colidx)):
            self.factorise2(len(self.colidx) - i - 1)

    def factorise2(self, n):
        remap = defaultdict(list)
        gone = []

        for i in range(0, len(self.rowidx)):
            v = self.one_less(i, n)
            s = remap[_as_tuple(v)]
            if len(s) != 0:
                gone.append(i)
            elem = self.get_elem(n, i)
            if elem not in s:
                s.append(elem)

        for g in reversed(gone):
            del self.rowidx[g]

        for i in range(0, len(self.rowidx)):
            v = self.one_less(i, n)
            s = remap[_as_tuple(v)]
            self.set_elem(n, i, _as_tuple(s))

    def sort_columns(self):
        """
        Sort the columns on the number of unique values (this column.diff).
        """
        for idx in self.colidx:
            self.cols[idx].compute_differences(self.rowidx)

        self.colidx.sort(key=lambda a: self.cols[a])

    def compare_rows(self, a, b):
        for idx in self.colidx:
            sa = self.cols[idx].value(a)
            sb = self.cols[idx].value(b)

            if sa is None and sb is None:
                continue

            if sa < sb:
                return -1

            if sa > sb:
                return 1

        return 0

    def sort_rows(self):
        self.rowidx.sort(key=cmp_to_key(self.compare_rows))

    def pop_singles(self):
        """
        Take the column with just one unique value and add them to the
        tree. Delete their index from the list of column indexes.
        """
        self.sort_columns()
        ok = False
        while len(self.colidx) > 0 and self.cols[self.colidx[0]].diff == 1:
            s = _as_tuple(self.get_elem(0, 0))
            self.tree._set_value(self.cols[self.colidx[0]].title, s)
            del self.colidx[0]
            ok = True

        return ok

    def split(self):
        if len(self.rowidx) < 2 or len(self.colidx) < 2:
            return

        self.sort_columns()
        self.sort_rows()

        prev = self.get_elem(0, 0)
        j = 0

        for i in range(1, len(self.rowidx)):
            e = self.get_elem(0, i)
            if prev != e:
                table = Table(self, j, i)
                self.tree._add_child(table.process())
                j = i
                prev = e

        if j > 0:
            table = Table(self, j, len(self.rowidx))
            self.tree._add_child(table.process())
            self.rowidx = []

    def process(self):
        self.factorise1()
        self.pop_singles()
        self.split()
        return self.tree


def _scan(r, cols, name, rest):
    """Generate all possible combinations of values. Each set of values is
    stored in a list and each value is repeated as many times so that if taking
    one row in all value lists, I will get one unique combination of values
    between all input keys.

    @param r    request as a dict
    @param cols actual result of the _scan
    @param name current request key we are processing
    @param rest remaining request keys to process
    """
    n = 0
    # print("Scan", name)
    c = cols[name]
    for value in r.get(name, ["-"]):
        m = 1
        if rest:
            m = _scan(r, cols, rest[0], rest[1:])
        for _ in range(0, m):
            c.append(value)
        n += m

    return n


def _as_requests(r):

    s = {}
    for k, v in r.items():
        if not isinstance(v, (tuple, list)):
            s[k] = [v]
        else:
            s[k] = v

    return s


def factorise(req, compress=False, intervals=[]):
    return _factorise(deepcopy(req), compress, intervals)


def _factorise(req, compress=True, intervals=[]):

    if compress:
        compress = Compressor()

    if intervals:
        for r in req:
            for i in intervals:
                if i in r:
                    r[i] = _as_interval(r[i])

    for i in intervals:
        # Collect all dates
        dates = set()
        for r in req:
            for interval in r.get(i, []):
                dates.add(interval.start)
                dates.add(interval.end)

        # Split intervals according to collected dates
        for r in req:
            if i in r:
                splits = []
                for interval in r.get(i, []):
                    splits.extend(interval.split(dates))
                r[i] = splits

    # if compress:
    #     compress.encode_requests(req)

    req = [_as_requests(r) for r in req]

    names = list(set(name for r in req for name in r.keys()))
    # print(names)

    cols = defaultdict(list)
    if names:
        for r in req:
            _scan(r, cols, names[0], names[1:])

    table = Table()
    for n, c in cols.items():
        # print(n, len(c))
        table.column(n, c)

    tree = table.process()

    # if compress:
    #     compress.decode_tree([r])

    for i in intervals:
        tree._join_intervals(i)

    return tree