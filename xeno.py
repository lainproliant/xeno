# Xeno: The Python dependency injector from outer space.
#
# Author: Lain Supe (lainproliant)
# Date: Sunday, August 28th 2016
#
# Released under a 3-clause BSD license, see LICENSE for more info.
__all__ = [
    "InjectionError",
    "MissingResourceError",
    "MissingDependencyError",
    "MethodInjectionError",
    "ClassInjectionError",
    "CircularDependencyError",
    "UndefinedNameError",
    "UnknownNamespaceError",
    "InvalidResourceError",
    "ClassAttributes",
    "MethodAttributes",
    "Namespace",
    "async_map",
    "async_wrap",
    "singleton",
    "provide",
    "inject",
    "named",
    "alias",
    "namespace",
    "const",
    "using",
    "scan_methods",
    "get_injection_points",
    "get_providers",
    "get_injection_params",
    "Injector",
]


import asyncio
import inspect


NOTHING = object()


class InjectionError(Exception):
    pass


class MissingResourceError(InjectionError):
    def __init__(self, name):
        super().__init__('The resource "%s" was not provided.' % name)
        self.name = name


class MissingDependencyError(InjectionError):
    def __init__(self, name, dep_name):
        super().__init__(
            f'Resource "{dep_name}" required by "{name}" was not provided.')
        self.name = name
        self.dep_name = dep_name


class MethodInjectionError(InjectionError):
    def __init__(self, method, name, reason=None):
        super().__init__(
            f'Failed to inject "{name}" into {method.__qualname__}'
            + f': {reason}' if reason else '.'
        )
        self.method = method
        self.name = name


class ClassInjectionError(InjectionError):
    def __init__(self, class_, name, reason=None):
        super().__init__(
            'Failed to inject "%s" into constructor for class "%s".'
            % (name, class_.__qualname__)
            + reason
            or ""
        )
        self.class_ = class_
        self.name = name


class CircularDependencyError(InjectionError):
    def __init__(self, resource, dep):
        super().__init__(
            'Circular dependency detected between "%s" and "%s".' % (
                resource, dep)
        )
        self.resource = resource
        self.dep = dep


class UndefinedNameError(InjectionError):
    def __init__(self, name):
        super().__init__('Undefined name: "%s"' % name)
        self.name = name


class UnknownNamespaceError(InjectionError):
    def __init__(self, name):
        super().__init__('Unknown namespace: "%s"' % name)
        self.name = name


class InvalidResourceError(InjectionError):
    pass


class Attributes:
    def __init__(self):
        self.attr_map = {}

    @staticmethod
    def for_object(obj, create=True, write=False,
                   factory=lambda: Attributes()):
        try:
            return obj._attrs

        except AttributeError:
            if create:
                attrs = factory(obj)
                if write:
                    obj._attrs = attrs
                return attrs
            else:
                return None

    def put(self, attr, value=True):
        self.attr_map[attr] = value
        return self

    def get(self, attr, default_value=NOTHING):
        if attr in self.attr_map:
            return self.attr_map[attr]
        elif default_value is NOTHING:
            raise AttributeError("No such attribute: %s" % attr)
        else:
            return default_value

    def check(self, attr):
        return True if self.get(attr, None) else False

    def merge(self, attr):
        self.attr_map.update(attr.attr_map)
        return self


class ClassAttributes(Attributes):
    @staticmethod
    def for_class(class_, create=True, write=False):
        return Attributes.for_object(
            class_, create, write, factory=lambda x: ClassAttributes(x)
        )

    @staticmethod
    def for_object(obj, create=True, write=False):
        return ClassAttributes.for_class(obj.__class__, create, write)

    def __init__(self, class_):
        super().__init__()
        self.put("name", class_.__name__)
        self.put("qualname", class_.__qualname__)


class MethodAttributes(Attributes):
    @staticmethod
    def for_method(f, create=True, write=False):
        return Attributes.for_object(
            f, create, write, factory=lambda x: MethodAttributes(x)
        )

    @staticmethod
    def wraps(f1):
        def decorator(f2):
            attr1 = MethodAttributes.for_method(f1)
            MethodAttributes.for_method(f2, write=True).merge(attr1)
            return f2

        return decorator

    @staticmethod
    def add(name, value=True):
        def decorator(f):
            attrs = MethodAttributes.for_method(f, write=True)
            attrs.put(name, value)
            return f

        return decorator

    def __init__(self, f):
        super().__init__()
        self.put("name", f.__name__)
        self.put("qualname", f.__qualname__)
        self.put("params", get_params_from_signature(f))


class Namespace:
    ROOT = "@root"
    SEP = "/"

    @staticmethod
    def join(*args):
        return Namespace.SEP.join(args)

    @staticmethod
    def root():
        return Namespace(Namespace.ROOT)

    @staticmethod
    def leaf_name(name):
        return name.split(Namespace.SEP)[-1]

    def __init__(self, name):
        self.name = name
        self.sub_namespaces = {}
        self.leaves = set()

    def add(self, name):
        if not name:
            raise ValueError("Leaf node name is empty!")
        parts = name.split(Namespace.SEP)
        if len(parts) == 1:
            if name in self.sub_namespaces:
                raise ValueError(
                    'Leaf node cannot have the same name as an existing '
                    'namespace: "%s"'
                    % name
                )
            self.leaves.add(name)
        else:
            if not parts[0] in self.sub_namespaces:
                if parts[0] in self.leaves:
                    raise ValueError(
                        'Namespace cannot have the same name as an existing '
                        'leaf node: "%s"'
                        % parts[0]
                    )
                self.sub_namespaces[parts[0]] = Namespace(parts[0])
            namespace = self.sub_namespaces[parts[0]]
            namespace.add(Namespace.join(*parts[1:]))

    def add_namespace(self, name):
        if not name:
            raise ValueError("Namespace name is empty!")
        parts = name.split(Namespace.SEP)
        ns = self
        for part in parts:
            if part in ns.sub_namespaces:
                ns = ns.sub_namespaces[part]
            else:
                new_ns = Namespace(part)
                ns.sub_namespaces[part] = new_ns
                ns = new_ns

    def get_namespace(self, name=None):
        if name == Namespace.SEP or not name:
            return self
        elif name.startswith(Namespace.SEP):
            return self.get_namespace(name[1:])
        else:
            nodes = name.split(Namespace.SEP)
            if nodes[0] in self.sub_namespaces:
                return self.sub_namespaces[nodes[0]].get_namespace(
                    Namespace.SEP.join(nodes[1:])
                )
            else:
                return None

    def get_leaves(self, recursive=False, prefix=""):
        if not recursive:
            return list(self.leaves)
        else:
            if self.name == Namespace.ROOT:
                prefix = ""
            else:
                prefix += self.name + Namespace.SEP

            leaves = []
            leaves.extend([prefix + x for x in self.leaves])
            for ns in self.sub_namespaces.values():
                leaves.extend(ns.get_leaves(True, prefix))
            return leaves


async def async_map(key, coro):
    """
    Wraps a coroutine so that when executed, the coroutine result
    and the mapped value are provided.  Useful for gathering results
    from a map of coroutines.
    """
    return key, await coro


async def async_wrap(f, *args, **kwargs):
    """
    Wraps a normal function in a coroutine.  If the given function
    is already a coroutine function, we simply yield from it.
    """
    if not asyncio.iscoroutinefunction(f):
        return f(*args, **kwargs)
    else:
        return await f(*args, **kwargs)


def singleton(f):
    """
    Method annotation indicating a named singleton resource.

    The function will only ever be invoked on an instance of the
    module once, and the return value will be provided to all
    injected objects that require it.
    """

    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("singleton")
    attrs.put("provider")
    return f


def provide(f):
    """
    Method annotation indicating a named resource.

    The function will be added to the Injector's resource map and
    called each time an injected instance is created that requires
    the resource.
    """

    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("provider")
    return f


def inject(f):
    """
    Method annotation indicating an injection point in an object.

    Instance methods marked with @inject are called after an object
    is created via Injector.create() or if an instance is passed
    to Injector.inject().

    All of the parameters of a method marked with @inject must refer
    to named resources in the Injector, or must provide default values
    which can be overridden by resources in the injector.
    """
    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("injection-point")
    return f


def named(name):
    """
    Method annotation indicating a name for the given resource other
    than the name of the method itself.
    """

    def impl(f):
        attrs = MethodAttributes.for_method(f, write=True)
        attrs.put("name", name)
        return f

    return impl


def alias(alias, name):
    """
    Aliases a single resource to a different name in the given
    module or resource context.
    """

    def impl(obj):
        attrs = None
        if inspect.isclass(obj):
            attrs = ClassAttributes.for_class(obj, write=True)
        else:
            attrs = MethodAttributes.for_method(obj, write=True)
        aliases = attrs.get("aliases", {})
        aliases[alias] = name
        attrs.put("aliases", aliases)
        return obj

    return impl


def namespace(name):
    """
    Module annotation indicating that the resources defined inside
    should be scoped into the given namespace, that is the given
    string is appended to all resource names followed by '/'.
    """

    def impl(class_):
        attrs = ClassAttributes.for_class(class_, write=True)
        attrs.put("namespace", name)
        return class_

    return impl


def const(name, value):
    """
    Module annotation defining a constant resource scoped into the
    module's namespace.
    """

    def impl(class_):
        attrs = ClassAttributes.for_class(class_, write=True)
        const_map = attrs.get("const_map", {})
        const_map[name] = value
        attrs.put("const_map", const_map)
        return class_

    return impl


def using(name):
    def impl(obj):
        attrs = None
        if inspect.isclass(obj):
            attrs = ClassAttributes.for_class(obj, write=True)
        else:
            attrs = MethodAttributes.for_method(obj, write=True)
        namespaces = attrs.get("using-namespaces", [])
        namespaces.append(name)
        attrs.put("using-namespaces", namespaces)
        return obj

    return impl


def bind_unbound_method(obj, method):
    return method.__get__(obj, obj.__class__)


def scan_methods(obj, filter_f):
    """
    Scan the object for methods that match the given attribute filter
    and return them as a stream of tuples.
    """
    for class_ in inspect.getmro(obj.__class__):
        for name, method in inspect.getmembers(class_,
                                               predicate=inspect.isfunction):
            attrs = MethodAttributes.for_method(method, create=False)
            if attrs is not None and filter_f(attrs):
                yield (attrs, bind_unbound_method(obj, method))


def get_injection_points(obj):
    """
    Scan the object and all of its parents for injection points
    and return them as a stream of tuples.
    """

    return scan_methods(obj, lambda attr: attr.check("injection-point"))


def get_providers(obj):
    """
    Scan the object and all of its parents for providers and return
    them as a stream of tuples.
    """

    return scan_methods(obj, lambda attr: attr.check("provider"))


def get_params_from_signature(f):
    """
    Fetches the params tuple list from the given function's signature.
    """
    sig = inspect.signature(f)
    return list(sig.parameters.values())


def get_injection_params(f, unbound_ctor=False):
    """
    Fetches the injectable parameter names of parameters to the given
    method, along with a set of parameters which have default values
    and should be considered optional dependencies.

    This method will throw InjectionError if the method provided has
    arguments that are not POSITIONAL_OR_KEYWORD or KEYWORD_ONLY.

    If the method provided is an unbound object constructor,
    unbound_ctor must be set to True to prevent 'self' from being
    returned by this method as an injectable parameter.
    """
    injection_param_names = []
    default_param_set = set()
    params = []

    if not inspect.ismethod(f) and unbound_ctor and not inspect.isfunction(f):
        # We do not want to try to inject a slot wrapper
        # version of __init__, as its params are (*args, **kwargs)
        # and it does nothing anyway.
        return [], set()

    attr = MethodAttributes.for_method(f)
    if attr.check("params"):
        params = attr.get("params")
    else:
        params = get_params_from_signature(f)

    if inspect.ismethod(f) or unbound_ctor:
        # Don't try to inject the 'self' parameter of an
        # unbound constructor.
        params = params[1:]

    for param in params:
        if param.kind in [
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ]:
            if param.default != param.empty:
                default_param_set.add(param.name)
            injection_param_names.append(param.name)
        else:
            raise InjectionError(
                "Xeno only supports injection of POSITIONAL_OR_KEYWORD and "
                "KEYWORD_ONLY arguments, %s arguments (%s of %s) "
                "are not supported."
                % (param.kind, param.name, f.__qualname__)
            )
    return injection_param_names, default_param_set


def resolve_alias(name, aliases, visited=None):
    if visited is None:
        visited = set()

    if name in aliases:
        if name in visited:
            raise InjectionError(
                "Alias loop detected: %s -> %s" % (name, ",".join(visited))
            )
        visited.add(name)
        name = resolve_alias(aliases[name], aliases, set(visited))
    return name


class Injector:
    """
    An object responsible for collecting resources from modules and
    injecting them into newly created instances.

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
        self.loop = asyncio.get_event_loop()
        self.resources = {"injector": lambda: self}
        self.singletons = {}
        self.dep_graph = {}
        self.injection_interceptors = []
        self.async_injection_interceptors = []
        self.ns_index = Namespace.root()
        self.resource_attrs = {}

        for module in modules:
            self.add_module(module, skip_cycle_check=True)
        self._check_for_cycles()

    def get_namespace(self, name=None):
        if name is None or name == Namespace.SEP:
            return self.ns_index
        else:
            return self.ns_index.get_namespace(name)

    def add_module(self, module, skip_cycle_check=False):
        """
        Add a module to the injector.  The module is scanned for @provider
        annotated methods, and these methods are added as resources to
        the injector.
        """
        module_attrs = ClassAttributes.for_class(module.__class__)
        namespace = module_attrs.get("namespace", None)
        using_namespaces = []
        if namespace is not None:
            using_namespaces.append(namespace)
            self.ns_index.add_namespace(namespace)
        module_aliases = self._get_aliases(module_attrs, using_namespaces)
        for name, value in module_attrs.get("const_map", {}).items():
            self.provide(name, value, is_singleton=True, namespace=namespace)
        for attrs, provider in get_providers(module):
            self._bind_resource(provider, module_aliases, namespace)

        if not skip_cycle_check:
            self._check_for_cycles()

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

    def add_async_injection_interceptor(self, interceptor):
        self.async_injection_interceptors.append(interceptor)

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
        return self.loop.run_until_complete(self.create_async(class_))

    async def create_async(self, class_):
        """
        Create an instance of the specified class.  The class' constructor
        must follow the rules for @inject methods, such that all of its
        parameters refer to injectable resources or are optional.

        This async method is meant to be awaited from another coroutine.

        If the object needs to be constructed with objects not from the
        Injector, do not use this method.  Instead, instantiate the object
        with these parameters in the constructor, then mark one or more
        methods with @inject and pass the instance to Injector.inject().
        """
        try:
            param_map, alias_map = await self._resolve_dependencies(
                class_.__init__, unbound_ctor=True
            )
            attrs = MethodAttributes.for_method(class_.__init__)
            param_map = await self._invoke_injection_interceptors(
                attrs, param_map, alias_map
            )
        except MethodInjectionError as e:
            raise ClassInjectionError(class_, e.name)

        instance = class_(**param_map)
        await self._inject_instance(instance)
        return instance

    def inject(self, obj, aliases={}, namespace=""):
        """
        Inject a method or object instance with resources from this Injector.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an
             instance, its methods are scanned for injection points and these
             methods are all invoked with resources from the Injector.
        aliases: An optional map from dependency alias to real dependency name.
        """
        return self.loop.run_until_complete(
            self.inject_async(obj, aliases, namespace))

    async def inject_async(self, obj, aliases={}, namespace=""):
        """
        Inject a method or object instance with resources from this Injector.

        This async method is meant to be awaited from another coroutine.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an
             instance, its methods are scanned for injection points and these
             methods are all invoked with resources from the Injector.
        aliases: An optional map from dependency alias to real dependency name.
        """
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            return await self._inject_method(obj, aliases, namespace)
        else:
            return await self._inject_instance(obj, aliases, namespace)

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
        return self.loop.run_until_complete(self.require_async(name, method))

    async def require_async(self, name, method=None):
        """
        Require a named resource from this Injector.  If it can't be provided,
        an InjectionError is raised.

        This async method is meant to be awaited from another coroutine.

        Optionally, a method can be specified.  This indicates the method that
        requires the resource for injection, and causes this method to throw
        MethodInjectionError instead of InjectionError if the resource was
        not provided.
        """
        return await self._require_coro(name, method)

    async def provide_async(self, name, value, is_singleton=False,
                            namespace=None):
        if name in self.singletons:
            del self.singletons[name]
        if inspect.ismethod(value) or inspect.isfunction(value):
            if is_singleton:
                value = singleton(value)
            await self._bind_resource_async(value, namespace=namespace)
        else:

            @named(name)
            def wrapper():
                return value

            if is_singleton:
                wrapper = singleton(wrapper)
            await self._bind_resource_async(wrapper, namespace=namespace)

    def provide(self, name, value, is_singleton=False, namespace=None):
        return self.loop.run_until_complete(
            self.provide_async(name, value, is_singleton, namespace)
        )

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
            dep_graph = {name: self.get_dependencies(name)
                         for name in resource_names}
            for dep in dep_graph[resource_name]:
                dep_graph.update(self.get_dependency_graph(dep))
            return dep_graph
        except MissingResourceError as e:
            raise MissingDependencyError(resource_name, e.name)

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
            if not self.get_resource_attributes(resource_name).check(
                    "singleton"):
                raise InvalidResourceError(
                    'Resource "%s" is not a singleton.' % resource_name
                )
            if resource_name in self.singletons:
                del self.singletons[resource_name]

    async def _bind_resource_async(
        self, bound_method, module_aliases={}, namespace=None
    ):
        params, _ = get_injection_params(bound_method)
        attrs = MethodAttributes.for_method(bound_method)

        using_namespaces = []
        name = attrs.get("name")
        # Allow names that begin with the namespace separator
        # to be scoped outside of the specified namespace.
        if name.startswith(Namespace.SEP):
            name = name[len(Namespace.SEP):]
        elif namespace is not None:
            name = Namespace.join(namespace, name)
            using_namespaces.append(namespace)

        def get_aliases(name):
            aliases = {
                **(self._get_aliases(attrs, using_namespaces) or {}),
                **module_aliases,
            }
            return aliases

        aliases = get_aliases(name)
        print(repr(aliases))
        injected_method = await self.inject_async(bound_method, aliases,
                                                  namespace)

        if attrs.check("singleton"):

            async def wrapper():
                if name not in self.singletons:
                    singleton = await injected_method()
                    self.singletons[name] = singleton
                    return singleton
                else:
                    return self.singletons[name]

            resource = wrapper
        else:
            resource = injected_method

        # Make the canonical full resource name available via 'resource-name'.
        attrs.put("resource-name", name)

        self.ns_index.add(name)
        self.resources[name] = resource
        self.resource_attrs[name] = attrs
        self.dep_graph[name] = lambda: [
            resolve_alias(x, get_aliases(x)) for x in params
        ]

    def _bind_resource(self, bound_method, module_aliases={}, namespace=None):
        return self.loop.run_until_complete(
            self._bind_resource_async(bound_method, module_aliases, namespace)
        )

    def _check_for_cycles(self):
        def visit(resource, visited=None):
            if visited is None:
                visited = set()
            visited.add(resource)
            for dep in self.dep_graph.get(resource, lambda: ())():
                if dep in visited:
                    raise CircularDependencyError(resource, dep)
                else:
                    visit(dep, set(visited))

        for resource in self.dep_graph.keys():
            visit(resource)

    async def _resolve_dependencies(
        self, f, unbound_ctor=False, aliases={}, namespace=""
    ):
        params, default_set = get_injection_params(
            f, unbound_ctor=unbound_ctor)
        attrs = MethodAttributes.for_method(f)
        param_map = {}
        param_resource_map = {}
        full_name = attrs.get("name")
        if namespace:
            full_name = Namespace.join(namespace, full_name)
            aliases = {**aliases, **self._get_aliases(attrs, [namespace])}

        try:
            resource_async_map = {}
            for param in params:
                if param in default_set and not self.has(param):
                    continue
                resource_name = param
                if resource_name.startswith(Namespace.SEP):
                    resource_name = resource_name[len(Namespace.SEP):]
                resource_name = resolve_alias(resource_name, aliases)
                resource_async_map[param] = self._require_coro(resource_name)
                param_resource_map[param] = resource_name

            for k, c in resource_async_map.items():
                param_map[k] = await c

        except MissingResourceError as e:
            raise MissingDependencyError(full_name, e.name) from e
        return param_map, param_resource_map

    async def _inject_instance(self, instance, aliases={}, namespace=""):
        class_attributes = ClassAttributes.for_class(instance.__class__)
        aliases = {**aliases, **class_attributes.get("aliases", {})}
        for attrs, injection_point in get_injection_points(instance):
            injected_method = await self.inject_async(
                injection_point, aliases, namespace
            )
            await injected_method()
        return instance

    async def _inject_method(self, method, aliases_in={}, namespace=""):
        async def wrapper():
            aliases = {**aliases_in}
            attrs = MethodAttributes.for_method(method)
            aliases = {**aliases, **attrs.get("aliases", {})}
            param_map, alias_map = await self._resolve_dependencies(
                method, aliases=aliases, namespace=namespace
            )
            param_map = await self._invoke_injection_interceptors(
                attrs, param_map, alias_map
            )
            return await async_wrap(method, **param_map)

        return wrapper

    async def _invoke_injection_interceptors(self, attrs, param_map,
                                             alias_map):
        for interceptor in self.injection_interceptors:
            param_map = interceptor(attrs, param_map, alias_map)
        for interceptor in self.async_injection_interceptors:
            param_map = await interceptor(attrs, param_map, alias_map)
        return param_map

    def _get_aliases(self, attrs, namespaces=[]):
        aliases = attrs.get("aliases", {})
        for alias in aliases.keys():
            if Namespace.SEP in alias:
                raise InjectionError(
                    'Alias name may not contain the namespace '
                    'separator: "%s"' % alias
                )
        using_namespaces = namespaces + attrs.get("using-namespaces", [])
        for namespace in using_namespaces:
            aliases = {
                **aliases,
                **{
                    Namespace.leaf_name(name): name
                    for name in self.ns_index.get_leaves(recursive=True)
                },
            }
        return aliases

    async def _require_coro(self, name, method=None):
        """
        For internal use only.  Used to tie together resources needed
        by other resources in this injector.
        """
        if name not in self.resources:
            if method is not None:
                raise MethodInjectionError(method, name,
                                           "Resource was not provided.")
            else:
                raise MissingResourceError(name)
        else:
            if name in self.singletons:
                return self.singletons[name]
            else:
                return await async_wrap(self.resources[name])

