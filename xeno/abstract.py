# --------------------------------------------------------------------
# abstract_injector.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------


from abc import ABCMeta, abstractmethod
from typing import Any, List, Optional, Set

from .attributes import NOTHING, ClassAttributes, get_providers
from .decorators import Tags
from .errors import (
    CircularDependencyError,
    InjectionError,
    InvalidResourceError,
    MissingDependencyError,
    MissingResourceError,
)
from .namespaces import Namespace


# --------------------------------------------------------------------
class AbstractInjector(metaclass=ABCMeta):
    """
    This is the abstract base class for injectors.

    An injector is responsible for collecting resources from modules and
    injecting them into newly created instances and/or providing them
    when explicitly required.

    An Injector is instantianted with any number of modules, which
    provide resources via methods annotated with @provide.  These
    methods are allowed to depend on other resources, potentially
    from myriad other modules, in order to generate their
    dependencies.

    Evaulation and injection of dependencies is lazy, meaning that
    the dependency graph is not evaluated until a resource is
    requested.
    """

    def __init__(self, *modules):
        """
        Create an Injector object.

        *modules: A list of modules to include in the injector.
                  More modules can be added later by calling
                  Injector.add_module().
        """
        self.resources: dict[str, Any] = {"injector": lambda: self}
        self.singletons = {}
        self.dep_graph = {}
        self.injection_interceptors = []
        self.ns_index = Namespace.root()
        self.resource_attrs = {}

        for module in modules:
            self.add_module(module, skip_cycle_check=True)
        self.check_for_cycles()

    @abstractmethod
    def create(self, class_):
        """
        Create an instance of the specified class.  The class' constructor
        must follow the rules for @inject methods, such that all of its
        parameters refer to injectable resources or are optional.

        If the object needs to be constructed with objects not from the
        Injector, do not use this method.  Instead, instantiate the object
        with these parameters in the constructor, then mark one or more
        methods with @inject and pass the instance to Injector.inject().
        """
        raise NotImplementedError()

    @abstractmethod
    def inject(self, obj, aliases={}, namespace=""):
        """
        Inject a method or object instance with resources from this Injector.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an
             instance, its methods are scanned for injection points and these
             methods are all invoked with resources from the Injector.
        aliases: An optional map from dependency alias to real dependency name.
        """
        raise NotImplementedError()

    @abstractmethod
    def require(self, name, method=None):
        """
        Require a named resource from this Injector.  If it can't be provided,
        an InjectionError is raised.

        This method should only be called from outside of the asyncio
        event loop.

        Optionally, a method can be specified.  This indicates the method that
        requires the resource for injection, and causes this method to throw
        MethodInjectionError instead of InjectionError if the resource was
        not provided.
        """
        raise NotImplementedError()

    @abstractmethod
    def provide(
        self, name_or_method, value=NOTHING, is_singleton=False, namespace=None
    ):
        raise NotImplementedError()

    @abstractmethod
    def _bind_resource(self, bound_method, module_aliases={}, namespace=None):
        raise NotImplementedError()

    def get_namespace(self, name=None) -> Optional[Namespace]:
        if name is None or name == Namespace.SEP:
            return self.ns_index
        return self.ns_index.get_namespace(name)

    def add_module(self, module, skip_cycle_check=False):
        """
        Add a module to the injector.  The module is scanned for @provider
        annotated methods, and these methods are added as resources to
        the injector.
        """
        module_attrs = ClassAttributes.for_class(module.__class__)
        assert module_attrs is not None
        namespace = module_attrs.get(Tags.NAMESPACE, None)
        using_namespaces = []
        if namespace is not None:
            using_namespaces.append(namespace)
            self.ns_index.add_namespace(namespace)
        module_aliases = self._get_aliases(module_attrs, using_namespaces)
        for name, value in module_attrs.get(Tags.CONST_MAP, {}).items():
            self.provide(name, value, is_singleton=True, namespace=namespace)
        for _, provider in get_providers(module):
            self._bind_resource(provider, module_aliases, namespace)

        if not skip_cycle_check:
            self.check_for_cycles()

    def add_injection_interceptor(self, interceptor):
        """
        Specifies a function to be called before resources are injected into
        a provider, constructor, or injection point.  Resources are provided
        to the function as a key/value map.

        The injection interceptor is expected to return a key/value map
        containing all of the resources provided to it, either modified
        or in their original form.  Failure to provide all required
        resources will lead to an InjectionError after the interceptors
        are invoked.
        """
        self.injection_interceptors.append(interceptor)

    def has(self, name):
        """
        Determine if this Injector has been provided with the named resource.
        """
        return name in self.resources

    def get_dependency_tree(self, resource_name):
        if resource_name not in self.resources:
            raise MissingResourceError(resource_name)
        try:
            return {
                dep: self.get_dependency_tree(dep)
                for dep in self.get_dependencies(resource_name)
            }
        except MissingResourceError as e:
            raise MissingDependencyError(resource_name, e.name)

    def get_dependency_graph(self, resource_name, *other_resource_names):
        resource_names = [resource_name, *other_resource_names]
        for name in resource_names:
            if name not in self.resources:
                raise MissingResourceError(name)
        try:
            dep_graph = {name: self.get_dependencies(name) for name in resource_names}
            for dep in dep_graph[resource_name]:
                dep_graph.update(self.get_dependency_graph(dep))
            return dep_graph
        except MissingResourceError as e:
            raise MissingDependencyError(resource_name, e.name)

    def get_ordered_dependencies(self, resource_name):
        deps: List[str] = []
        visited: Set[str] = set()
        stack: List[str] = [resource_name]

        while stack:
            name = stack.pop()
            if name not in visited:
                visited.add(name)
                if not name == resource_name:
                    deps.append(name)
                stack.extend(self.get_dependencies(name))

        return deps

    def get_dependencies(self, resource_name):
        return self.dep_graph.get(resource_name, lambda: ())()

    def get_resource_attributes(self, resource_name):
        if resource_name not in self.resource_attrs:
            raise MissingResourceError(resource_name)
        return self.resource_attrs[resource_name]

    def scan_resources(self, filter_f):
        for key, value in self.resource_attrs.items():
            if filter_f(key, value):
                yield key, value

    def unbind_singleton(self, resource_name=None, unbind_all=False):
        if unbind_all:
            self.singletons.clear()
        else:
            if resource_name not in self.resources:
                raise MissingResourceError(resource_name)
            if not self.get_resource_attributes(resource_name).check(Tags.SINGLETON):
                raise InvalidResourceError(
                    'Resource "%s" is not a singleton.' % resource_name
                )
            if resource_name in self.singletons:
                del self.singletons[resource_name]

    def check_for_cycles(self):
        def visit(resource, visited=None):
            if visited is None:
                visited = set()
            visited.add(resource)
            for dep in self.dep_graph.get(resource, lambda: ())():
                if dep in visited:
                    raise CircularDependencyError(resource, dep)
                visit(dep, set(visited))

        for resource in self.dep_graph:
            visit(resource)

    def _get_aliases(self, attrs, namespaces=[]):
        aliases = attrs.get(Tags.ALIASES, {})
        for alias in aliases.keys():
            if Namespace.SEP in alias:
                raise InjectionError(
                    "Alias name may not contain the namespace "
                    'separator: "%s"' % alias
                )
        using_namespaces = namespaces + attrs.get(Tags.USING_NAMESPACES, [])
        for ns_name in using_namespaces:
            namespace = self.get_namespace(ns_name)
            assert namespace is not None
            aliases = {
                **aliases,
                **{
                    Namespace.leaf_name(name): Namespace.join(ns_name, name)
                    for name in namespace.get_leaves()
                },
            }
        return aliases

    def _invoke_injection_interceptors(self, attrs, param_map, alias_map):
        for interceptor in self.injection_interceptors:
            param_map = interceptor(attrs, param_map, alias_map)
        return param_map
