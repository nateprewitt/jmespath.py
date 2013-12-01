class Visitor(object):
    def visit(self, node, *args, **kwargs):
        method = getattr(
            self, 'visit_%s' % node.__class__.__name__,
            self.default_visit)
        return method(node, *args, **kwargs)

    def default_visit(self, node, *args, **kwargs):
        pass


class TreeInterpreter(Visitor):
    def _lookup_method(self, value, *methods):
        for method in methods:
            func = getattr(value, method, None)
            if func is not None:
                return func

    def visit_SubExpression(self, node, value):
        result = value
        for node in node.nodes:
            result = self.visit(node, result)
        return result

    def visit_Field(self, node, value):
        try:
            return value.get(node.name)
        except AttributeError:
            return None

    def visit_MultiFieldDict(self, node, value):
        if value is not None:
            method = getattr(value, 'multi_get', None)
            if method is not None:
                return method(node.nodes)
            else:
                collected = {}
                original = value
                for node in node.nodes:
                    current = self.visit(node, value)
                    collected[node.key_name] = current
                return collected

    def visit_MultiFieldList(self, node, value):
        if value is not None:
            method = getattr(value, 'multi_get_list', None)
            if method is not None:
                return method(node.nodes)
            else:
                collected = []
                for node in node.nodes:
                    current = self.visit(node, value)
                    collected.append(current)
                return collected

    def visit_KeyValPair(self, node, value):
        return self.visit(node.nodes[0], value)

    def visit_Index(self, node, value):
        # Even though we can index strings, we don't
        # want to support that.
        if not isinstance(value, list):
            return None
        else:
            method = self._lookup_method(value, 'get_index', '__getitem__')
            if method is not None:
                try:
                    return method(node.index)
                except IndexError:
                    return None

    def visit_WildcardIndex(self, node, value):
        return _Projection(value)

    def visit_WildcardValues(self, node, value):
        try:
            return _Projection(value.values())
        except AttributeError:
            return None

    def visit_ListElements(self, node, value):
        if isinstance(value, list):
            # reduce inner list elements into
            # a single list.
            merged_list = []
            for element in value:
                if isinstance(element, list):
                    merged_list.extend(element)
                else:
                    merged_list.append(element)
            return  _Projection(merged_list)
        else:
            return _Projection(value)

    def visit_ORExpression(self, node, value):
        result = self.visit(node.nodes[0], value)
        if result is None:
            result = self.visit(node.nodes[1], value)
        return result


class PrintVisitor(Visitor):
    def _print_node_with_children(self, node, indent=''):
        sub_indent = indent + ' ' * 4
        parts = ['%s%s(\n' % (indent, node.__class__.__name__)]
        for child in node.nodes[:-1]:
            parts.append('%s,\n' % (self.visit(child, sub_indent),))
        parts.append('%s)' % (self.visit(node.nodes[-1], sub_indent),))
        return ''.join(parts)

    def _print_leaf_node(self, node, indent, inner_content=''):
        return "%s%s(%s)" % (indent, node.__class__.__name__, inner_content)

    def visit_SubExpression(self, node, indent=''):
        return self._print_node_with_children(node, indent)

    def visit_Field(self, node, indent=''):
        return self._print_leaf_node(node, indent, node.name)

    def visit_MultiFieldDict(self, node, indent=''):
        return self._print_node_with_children(node, indent)

    def visit_MultiFieldList(self, node, indent=''):
        return self._print_node_with_children(node, indent)

    def visit_KeyValPair(self, node, indent=''):
        inner_content = 'key_name=%s, node=%s' % (node.key_name, node.nodes[0])
        return self._print_leaf_node(node, indent, inner_content)

    def visit_Index(self, node, indent=''):
        return self._print_leaf_node(node, indent, node.index)

    def visit_WildcardIndex(self, node, indent=''):
        return self._print_leaf_node(node, indent, '*')

    def visit_WildcardValues(self, node, indent=''):
        return self._print_leaf_node(node, indent)

    def visit_ListElements(self, node, indent=''):
        return self._print_leaf_node(node, indent)

    def visit_ORExpression(self, node, indent=''):
        return self._print_node_with_children(node, indent)


class AST(object):
    def __init__(self, children_nodes=None):
        if children_nodes is None:
            children_nodes = []
        self.nodes = children_nodes

    def search(self, value):
        interpreter = TreeInterpreter()
        return interpreter.visit(self, value)

    def __repr__(self):
        printer = PrintVisitor()
        return printer.visit(self)

    def __eq__(self, other):
        return (isinstance(other, self.__class__)
                and self.__dict__ == other.__dict__)

    def __ne__(self, other):
        return not self.__eq__(other)


class SubExpression(AST):
    """Represents a subexpression match.

    A subexpression match has a parent and a child node.  A simple example
    would be something like 'foo.bar' which is represented as::

        SubExpression(Field(foo), Field(bar))

    """
    pass


class Field(AST):
    def __init__(self, name):
        super(Field, self).__init__()
        self.name = name


class MultiFieldDict(AST):
    pass


class MultiFieldList(AST):
    pass


class KeyValPair(AST):
    def __init__(self, key_name, node):
        super(KeyValPair, self).__init__(children_nodes=[node])
        self.key_name = key_name


class Index(AST):
    def __init__(self, index):
        super(Index, self).__init__()
        self.index = index


class WildcardIndex(AST):
    """Represents a wildcard index.

    For example::

        foo[*] -> SubExpression(Field(foo), WildcardIndex())

    """
    pass


class WildcardValues(AST):
    """Represents a wildcard on the values of a JSON object.

    For example::

        foo.* -> SubExpression(Field(foo), WildcardValues())

    """
    pass


class ListElements(AST):
    pass


class ORExpression(AST):
    pass


class _Projection(list):
    def __init__(self, elements):
        self.extend(elements)

    def get(self, value):
        results = self.__class__([])
        for element in self:
            try:
                result = element.get(value)
            except AttributeError:
                continue
            if result is not None:
                if isinstance(result, list):
                    result = self.__class__(result)
                results.append(result)
        return results

    def get_index(self, index):
        matches = []
        for el in self:
            if not isinstance(el, list):
                continue
            try:
                matches.append(el[index])
            except (IndexError, TypeError):
                pass
        return self.__class__(matches)

    def multi_get(self, nodes):
        results = self.__class__([])
        for element in self:
            if isinstance(element, self.__class__):
                result = element.multi_get(nodes)
            else:
                result = {}
                for node in nodes:
                    result[node.key_name] = node.search(element)
            results.append(result)
        return results

    def multi_get_list(self, nodes):
        results = self.__class__([])
        for element in self:
            if isinstance(element, self.__class__):
                result = element.multi_get_list(nodes)
            else:
                result = []
                for node in nodes:
                    result.append(node.search(element))
            results.append(result)
        return results

    def values(self):
        results = self.__class__([])
        for element in self:
            try:
                current = self.__class__(element.values())
                results.append(current)
            except AttributeError:
                continue
        return results
