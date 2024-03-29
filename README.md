# `xeno`: The Python dependency injector from outer space. 
[![Build Status](https://travis-ci.org/lainproliant/xeno.svg?branch=master)](https://travis-ci.org/lainproliant/xeno)

`xeno` at its core is a simple Python dependency injection framework. Use it when
you need to manage complex inter-object dependencies in a clean way. For the
merits of dependency injection and IOC, see
https://en.wikipedia.org/wiki/Dependency_injection.

`xeno` should feel pretty familiar to users of Google Guice in Java, as it
is somewhat similar, although it is less focused on type names and more
on named resources and parameter injection.

`xeno` also offers `xeno.build`, a build automation framework built atop the core
dependency injection inspired by [Invoke](https://www.pyinvoke.org/).  It is
intended to come with batteries-included tools for making C/C++ projects,
executing shell scripts, batching, and more.  It is built on the concept of
composable "recipes", which are generic instructions for building different
types of filesystem targets.


# Installation

Installation is simple. With python3-pip, do the following:

```
$ sudo pip install -e .
```

Or, to install the latest version available on PyPI:

```
$ sudo pip install xeno
```

# Usage
## As a build automation framework

To use `xeno.build` to build a simple C software project, first create a file
called `build.py` in your repo (it can be called anything, but this is
customary).  Follow this template example for guidance:

```
#!/usr/bin/env python3
from xeno.build import *

# TODO: Add recipes, providers, and tasks here.

build()
```

Then, you can import the `compile` recipe from `xeno.recipes.c`:

```
from xeno.recipes.c import compile, ENV
```

`ENV` here is the default environment variables that `compile` will use by
default.  It defaults to using `clang` to compile C projects, you can change
that here, and you can add additional compile-time flags.  The `ENV` object is
of type `xeno.shell.Environment`, which allows for some complex shlex-based
joining and recombining of flags, such that you can additively compose the
enviornment with defaults and/or what may be specified outside the build script.
You can also provide your own environment variables via the `env=` parameter to
`compile`.

```
ENV['CC'] = 'gcc'
ENV += dict(
    LDFLAGS='-g'
)
```

Let's create a provider that lists all of our source files and another that
lists our headers.  This will be useful for defining our tasks and using the
`compile` recipe.

```
from pathlib import Path

@provide
def source_files():
    return Path.cwd().glob("src/*.c")

@provide
def header_files():
    return Path.cwd().glob("include/*.h")
```

Next, let's define a single default task that builds our program.

```
@task(default=True)
def executable(source_files, header_files):
    return compile(source_files, target="my_program", headers=header_files)
```

`compile` can take iterables of source files and/or combinations of strings and
lists in `*args`.  In this case, we elected to specify a target name for the
program.  If this wasn't the case, the name of the resulting target would be
based on the name of the first source file.  This is ideal if there is only one
source being provided or if the main source file is always provided first and is
the desired name of the executable, but in this case it would be whatever came
first in the directory order which isn't deterministic or ideal.

Specifying the `headers=` parameter here links the recipe to our header files
as static file dependencies.  If these files change, the recipe is acknowledged
to be `outdated`, and will be rebuilt the next time the build script is run even
if an executable target already exists.

That's it!  Let's put it all together, and then we'll have a build script for
our program.

```
#!/usr/bin/env python3
from xeno.build import *
from xeno.recipes.c import compile, ENV
from pathlib import Path

ENV['CC'] = 'gcc'
ENV += dict(
    LDFLAGS='-g'
)

@provide
def source_files():
    return Path.cwd().glob("src/*.c")

@provide
def header_files():
    return Path.cwd().glob("include/*.h")

build()
```

Mark this script as executable and run it as `./build.py`, or use `python
build.py`.  Be sure to check out `./build.py --help` for a list of command line
options and running modes.  `xeno.build` is smart and can create addressable
targets from a variety of different nested recipe construction scenarios, so
build more complex scripts and try out `./build.py -L` to see them all!

Watch this space for more in-depth documentation to come in the near future.

## As an IOC framework

To use `xeno` as a dependency injection framework, you need to create a
xeno.Injector and provide it with modules. These modules are regular
Python objects with methods marked with the `@xeno.provider`
annotation. This annotation tells the `Injector` that this method
provides a named resource, the same name as the method marked with
`@provider`. These methods should either take no parameters (other
than `self`), or take named parameters which refer to other resources
by name, i.e. the providers can also be injected with other resources in
order to build a dependency chain.

Once you have an `Injector` full of resources, you can use it to
inject instances, functions, or methods with resources.

To create a new object instance by injecting resources into its
constructor, use `Injector.create(clazz)`, where `clazz` is the
class which you would like to instantiate. The constructor of this class
is called, and all named parameters in the constructor are treated as
resource references. Once the object is instantiated, any methods marked
with `@inject` are invoked with named resources provided.

Resources can be injected into normal functions, bound methods, or
existing object instances via `Injector.inject(obj)`. If the parameter
is an object instance, it is scanned for methods marked with `@inject`
and these methods are invoked with named resources provided.

### Example

In this simple example, we inject an output stream into an object.

```
import sys
from xeno import *

class OutputStreamModule:
   @provide
   def output_stream(self):
      return sys.stdout

class VersionWriter:
   def __init__(self, output_stream):
      self.output_stream = output_stream

   def write_version(self):
      print('The python version is %s' % sys.version_info,
            file=self.output_stream)

injector = Injector(OutputStreamModule())
writer = injector.create(VersionWriter)
writer.write_version()
```

Checkout `test.py` in the git repo for more usage examples.

## Change Log

### Version 7.3.0: Oct 9 2023
- `xeno.build` targets can now receive arguments!  All args after a lone '@' arg are packed into an
  implicit `argv` resource that can be injected into targets automatically.
- Fixed broken `run_as` functionality in `ShellRecipe`.

### Version 7.2.2: Oct 7 2023
- Add a `**kwargs` pass-thru for `xeno.shell.check()` for passing args to `subprocess.check_output()`.

### Version 7.2.1: Sep 15 2023
- Allow recipe factories to return empty results as None (or no explicit return value).

### Version 7.2.0: Sep 15 2023
- Improvements to the busy spinner: it now loops through pending recipe sigils
  to let the user know what is blocking in the build.
- Improved xeno.recipes.checkout() now opens `build.py` and checks its Python AST
  for references to "xeno" before trying to run "./build.py deps" if "build.py"
  is present in the resulting repository.

### Version 7.1.0: Sep 09 2023
- Add a `update()` override to `xeno.shell.Environment` which takes
  the same arguments as `select()` but updates the dictionary in-place
  instead of making and returning a new one.

### Version 7.0.0: Sep 09 2023
- Lift various build recipes from different projects into a
  "batteries-included" set of build tools under `xeno.recipes.**`.
- New enriched focus on backwards compatibility between minor versons.
- Restructuring and refactoring, `xeno.cookbook` is deprecated.
- From now on, legacy features will be marked as deprecated and made to
  continue to work until the next major version, during which they
  will be removed.

### Version 4.12.0: Aug 07 2022
- Changes to support Python 3.10, older versions are now deprecated.

### Version 4.10.0: Oct 28 2021
- Allow recipes to be specified with glob-style wildcards, as per `fnmatch`.

### Version 4.9.0: Jan 03 2021
- Deprecate `@recipe` factory decorator for `@factory`.
- Allow recipes to specify a `setup` recipe, which is not part
  of the recipe inputs or outputs but is needed to fulfill the task.

### Version 4.8.0: Dec 29 2020
- All recipe resources are loaded before targets are determined.
- Recipe names are now valid targets for a build.

### Version 4.7.0: Dec 16 2020
- Fixed a bug where build would continue resolving with outdated results.
- Added `@recipe` decorator to `xeno.build` to denote recipe functions.

### Version 4.4.0: Nov 2 2020
- Added experimental `xeno.build` module, a declarative build system driven by IOC.
- Added `xeno.color` offering basic ANSI color and terminal control.

### Version 4.3.0: May 9 2020
- Allow methods to be decorated with `@injector.provide`, eliminating the need for modules
  in some simple usage scenarios.

### Version 4.2.0: May 8 2020
- Split `Injector` into `AsyncInjector` and `SyncInjector` to allow injection to be performed
  in context of another event loop if async providers are not used.
- Fixed `AsyncInjector` to actually support asynchronous resolution of dependencies.

### Version 4.1.0: Feb 3 2020
- Added `Injector.get_ordered_dependencies` to get a breadth first list of
  dependencies in the order they are built.

### Version 4.0.0: May 12 2019
***BACKWARDS INCOMPATIBLE CHANGE***
- Removed support for parameter annotation aliases.  Use `@alias` on methods instead.
  This was removed to allow `xeno` code to play nicely with PEP 484 type hinting.

### Version 3.1.0: August 29 2018
- Add ClassAttributes.for_object convenience method

### Version 3.0.0: May 4 2018
***BACKWARDS INCOMPATIBLE CHANGE***
- Provide injection interceptors with an alias map for the given param map.
- This change breaks all existing injection interceptors until the new param is added.

### Version 2.8.0: May 3 2018
- Allow decorated/wrapped methods to be properly injected if their `'params'` method attribute
  is carried forward.

### Version 2.7.0: April 20 2018
- The `Injector` now adds a `'resource-name'` attribute to resource methods allowing
  the inspection of a resource's full canonical name at runtime.

### Version 2.6.0: March 27 2018
- Bugfix release: Remove support for implicit asynchronous resolution of
  dependencies.  Providers can still be async, in order to await some other
  set of coroutines, but can no longer themselves be run in sync.  The
  benefits do not outweigh the complexity of bugs and timing concerns
  introduced by this approach.

### Version 2.5.0: March 2, 2018
- Added `Injector.provide_async()`.  Note that resource are always run within an
  event loop and should not use `inject()`, `provide()`, or `require()`
  directly, instead they should use `inject_async()`, `provide_async()`, and
  `require_async()` to dynamically modify resources.

### Version 2.4.1: January 30, 2018
- Added `Injector.scan_resources()` to allow users to scan for resource names with the given attributes.
- Added `Attributes.merge()` to assist with passing attributes down to functions which are wrapped in a decorator.
- Added `MethodAttributes.wraps()` static decorator to summarize a common use case of attribute merging.
- Added `MethodAttributes.add()` as a simple static decorator to add attribute values to a method's attributes.

### Version 2.4.0: January 21, 2018
- Dropped support for deprecated `Namespace.enumerate()` in favor of `Namespace.get_leaves()`.

### Version 2.3.0: January 21, 2018
- Added support for asyncio-based concurrency and async provider coroutines with per-injector event loops (`injector.loop`).

### Version 2.2.0: September 19, 2017
- Expose the Injector's Namespace object via `Injector.get_namespace()`.  This is useful for users who want to list the contents of namespaces.

### Version 2.1.0: August 23rd, 2017
- Allow multiple resource names to be provided to `Injector.get_dependency_graph()`.

### Version 2.0.0: July 25th, 2017
***BACKWARDS INCOMPATIBLE CHANGE***
- Change the default namespace separator and breakout symbol to '/'

Code using the old namespace separator can be made to work by overriding the value of xeno.Namespace.SEP:
```
import xeno
xeno.Namespace.SEP = '::'
```

### Version 1.10: July 25th, 2017
- Allow names prefixed with `::` to escape their module's namespace, e.g. `::top_level_item`

### Version 1.9: May 23rd, 2017
- Add `@const()` module annotation for value-based resources
- Add `Injector.get_dependency_tree()` to fetch a tree of dependency names for a given resource name.

### Version 1.8: May 16th, 2017
- Add `MissingResourceError` and `MissingDependencyError` exception types.

### Version 1.7: May 16th, 2017
- Major update, adding support for namespaces, aliases, and inline resource parameter aliases.  See the unit tests in test.py for examples.
  - Added `@namespace('Name')` decorator for modules to specify that all resources defined in the module should be scoped within 'Name::'.
  - Added `@name('alt-name')` to allow resources to be named something other than the name of the function that defines them.
  - Added `@alias('alt-name', 'name')` to allow a resource to be renamed within either the scope of a single resource or a whole module.
  - Added `@using('NamespaceName')` to allow the contents of the given namespace
    to be automatically aliases into either the scope of a single resource or
    a whole module.
  - Added support for resource function annotations via PEP 3107 to allow
    inline aliases, e.g. `def my_resource(name: 'Name::something-important'):`

### Version 1.6: April 26th, 2017
- Changed how `xeno.MethodAttributes` works: it now holds a map of attributes
  and provides methods `get()`, `put()`, and `check()`

### Version 1.5: April 26th, 2017
- Added injection interceptors
- Refactored method tagging to use `xeno.MethodAttributes` instead of named
  object attributes to make attribute tagging more flexible and usable by
  the outside world, e.g. for the new injectors.

### Version 1.4: August 30th, 2016
- Added cycle detection.

### Version 1.3: August 29th, 2016
- Have the injector offer itself as a named resource named 'injector'.

