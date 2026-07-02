# Executors

Executors define how Parsl deploys work on a computer. Many types are available, each with different advantages.

The `HighThroughputExecutor`, like Python’s `ProcessPoolExecutor`, creates workers that are separate Python processes. However, you have much more control over how the work is deployed. You can dynamically set the number of workers based on available memory and pin each worker to specific GPUs or CPU cores among other powerful features.

Learn more about Executors here.

# Execution Providers

Resource providers allow Parsl to gain access to computing power. For supercomputers, gaining resources often requires requesting them from a scheduler (e.g., Slurm). Parsl Providers write the requests to requisition “Blocks” (e.g., supercomputer nodes) on your behalf. Parsl comes pre-packaged with Providers compatible with most supercomputers and some cloud computing services.

Another key role of Providers is defining how to start an Executor on a remote computer. Often, this simply involves specifying the correct Python environment and (described below) how to launch the Executor on each acquired computers.

Learn more about Providers here.

# Launchers

The Launcher defines how to spread workers across all nodes available in a Block. A common example is an `MPILauncher`, which uses MPI’s mechanism for starting a single program on multiple computing nodes. Like Providers, Parsl comes packaged with Launchers for most supercomputers and clouds.

Learn more about Launchers here.

# Benefits of a Data-Flow Kernel

The Data-Flow Kernel (DFK) is the behind-the-scenes engine behind Parsl. The DFK determines when tasks can be started and sends them to open resources, receives results, restarts failed tasks, propagates errors to dependent tasks, and performs the many other functions needed to execute complex workflows. The flexibility and performance of the DFK enables applications with intricate dependencies between tasks to execute on thousands of parallel workers.

Start with the Tutorial or the parallel patterns to see the complex types of workflows you can make with Parsl.

# Apps

In Parsl an app is a piece of code that can be asynchronously executed on an execution resource, such as a cloud, cluster, or local PC. Parsl provides support for pure Python apps, `python_app`, and also command-line apps executed via Bash, `bash_app`.

## Bash Apps

Parsl’s Bash app allows you to wrap execution of external applications from the command-line as you would in a Bash shell. It can also be used to execute Bash scripts directly. To define a Bash app, the wrapped Python function must return the command-line string to be executed.

As a first example of a Bash app, let’s use the Linux command `echo` to return the string `Hello World!`. This function is made into a Bash App using the `@bash_app` decorator.

Note that the `echo` command will print `Hello World!` to stdout. In order to use this output, we need to tell Parsl to capture stdout. This is done by specifying the `stdout` keyword argument in the app function. The same approach can be used to capture stderr.

```python
@bash_app
def echo_hello(stdout='echo-hello.stdout', stderr='echo-hello.stderr'):
    return 'echo "Hello World!"'

echo_hello().result()

with open('echo-hello.stdout', 'r') as f:
     print(f.read())
```

# Passing data

Parsl Apps can exchange data as Python objects, as shown above, or in the form of files. In order to enforce dataflow semantics, Parsl must track the data that is passed into and out of an App. To make Parsl aware of these dependencies, the app function includes `inputs` and `outputs` keyword arguments.

We first create three test files named `hello1.txt`, `hello2.txt`, and `hello3.txt` containing the text “hello 1”, “hello 2”, and “hello 3”.

```python
for i in range(3):
    with open(os.path.join(os.getcwd(), 'hello-{}.txt'.format(i)), 'w') as f:
        f.write('hello {}\n'.format(i))
```

We then write an App that will concentate these files using `cat`. We pass in the list of hello files, `inputs`, and concatenate the text into a new file named `all_hellos.txt`, `outputs`. As we describe below we use Parsl File objects to abstract file locations in the event the `cat` app is executed on a different computer.

```python
from parsl.data_provider.files import File

@bash_app
def cat(inputs, outputs):
    return 'cat {} > {}'.format(" ".join([i.filepath for i in inputs]), outputs[0])

concat = cat(inputs=[File(os.path.join(os.getcwd(), 'hello-0.txt')),
                    File(os.path.join(os.getcwd(), 'hello-1.txt')),
                    File(os.path.join(os.getcwd(), 'hello-2.txt'))],
             outputs=[File(os.path.join(os.getcwd(), 'all_hellos.txt'))])

# Open the concatenated file
with open(concat.outputs[0].result(), 'r') as f:
     print(f.read())
```

# Futures

When a normal Python function is invoked, the Python interpreter waits for the function to complete execution and returns the results. In case of long running functions, it may not be desirable to wait for completion. Instead, it is preferable that functions are executed asynchronously. Parsl provides such asynchronous behavior by returning a future in lieu of results. A future is essentially an object that allows Parsl to track the status of an asynchronous task so that it may, in the future, be interrogated to find the status, results, exceptions, etc.

Parsl provides two types of futures: AppFutures and DataFutures. While related, these two types of futures enable subtly different workflow patterns, as we will see.

## DataFutures

While AppFutures represent the execution of an asynchronous app, DataFutures represent the files it produces. Parsl’s dataflow model, in which data flows from one app to another via files, requires such a construct to enable apps to validate creation of required files and to subsequently resolve dependencies when input files are created. When invoking an app, Parsl requires that a list of output files be specified, using the `outputs` keyword argument. A DataFuture for each file is returned by the app when it is executed. Throughout execution of the app, Parsl will monitor these files to:

1. Ensure they are created.
2. Pass them to any dependent apps.

```python
# App that echos an input message to an output file
@bash_app
def slowecho(message, outputs):
    return 'sleep 5; echo %s &> %s' % (message, outputs[0])

# Call slowecho specifying the output file
hello = slowecho('Hello World!', outputs=[File(os.path.join(os.getcwd(), 'hello-world.txt'))])

# The AppFuture's outputs attribute is a list of DataFutures
print(hello.outputs)

# Also check the AppFuture
print('Done: {}'.format(hello.done()))

# Print the contents of the output DataFuture when complete
with open(hello.outputs[0].result(), 'r') as f:
     print(f.read())

# Now that this is complete, check the DataFutures again, and the Appfuture
print(hello.outputs)
print('Done: {}'.format(hello.done()))
```

# Data Management

Parsl is designed to enable implementation of dataflow patterns. These patterns enable workflows, in which the data passed between apps manages the flow of execution, to be defined. Dataflow programming models are popular as they can cleanly express, via implicit parallelism, the concurrency needed by many applications in a simple and intuitive way.

## Files

Parsl’s file abstraction abstracts access to a file irrespective of where the app is executed. When referencing a Parsl file in an app, by calling `filepath`, Parsl translates the path to the file’s location relative to the file system on which the app is executing.

```python
from parsl.data_provider.files import File

# App that copies the contents of a file to another file
@bash_app
def copy(inputs, outputs):
     return 'cat %s &> %s' % (inputs[0], outputs[0])

# Create a test file
open(os.path.join(os.getcwd(), 'cat-in.txt'), 'w').write('Hello World!\n')

# Create Parsl file objects
parsl_infile = File(os.path.join(os.getcwd(), 'cat-in.txt'),)
parsl_outfile = File(os.path.join(os.getcwd(), 'cat-out.txt'),)

# Call the copy app with the Parsl file
copy_future = copy(inputs=[parsl_infile], outputs=[parsl_outfile])

# Read what was redirected to the output file
with open(copy_future.outputs[0].result(), 'r') as f:
     print(f.read())
```

## Remote Files

The Parsl file abstraction can also represent remotely accessible files. In this case, you can instantiate a file object using the remote location of the file. Parsl will implictly stage the file to the execution environment before executing any dependent apps. Parsl will also translate the location of the file into a local file path so that any dependent apps can access the file in the same way as a local file. Parsl supports files that are accessible via Globus, FTP, and HTTP.

Here we create a File object using a publicly accessible file with random numbers. We can pass this file to the `sort_numbers` app in the same way we would a local file.

```python
from parsl.data_provider.files import File

@python_app
def sort_numbers(inputs):
    with open(inputs[0].filepath, 'r') as f:
        strs = [n.strip() for n in f.readlines()]
        strs.sort()
        return strs

unsorted_file = File('[remote file URL removed]')

f = sort_numbers(inputs=[unsorted_file])
print (f.result())
```

# Composing a workflow

Now that we understand all the building blocks, we can create workflows with Parsl. Unlike other workflow systems, Parsl creates implicit workflows based on the passing of control or data between Apps. The flexibility of this model allows for the creation of a wide range of workflows from sequential through to complex nested, parallel workflows. As we will see below, a range of workflows can be created by passing AppFutures and DataFutures between Apps.

## Sequential workflow

Simple sequential or procedural workflows can be created by passing an AppFuture from one task to another. The following example shows one such workflow, which first generates a random number and then writes it to a file.

```python
# App that generates a random number
@python_app
def generate(limit):
      from random import randint
      return randint(1,limit)

# App that writes a variable to a file
@bash_app
def save(variable, outputs):
      return 'echo %s &> %s' % (variable, outputs[0])

# Generate a random number between 1 and 10
random = generate(10)
print('Random number: %s' % random.result())

# Save the random number to a file
saved = save(random, outputs=[File(os.path.join(os.getcwd(), 'sequential-output.txt'))])

# Print the output file
with open(saved.outputs[0].result(), 'r') as f:
      print('File contents: %s' % f.read())
```

## Parallel workflow

The most common way that Parsl Apps are executed in parallel is via looping. The following example shows how a simple loop can be used to create many random numbers in parallel. Note that this takes 5 seconds to run, the time needed for the longest delay, not the 15 seconds that would be needed if these generate functions were called and returned in sequence.

```python
# App that generates a random number after a delay
@python_app
def generate(limit,delay):
    from random import randint
    import time
    time.sleep(delay)
    return randint(1,limit)

# Generate 5 random numbers between 1 and 10
rand_nums = []
for i in range(5):
    rand_nums.append(generate(10,i))

# Wait for all apps to finish and collect the results
outputs = [i.result() for i in rand_nums]

# Print results
print(outputs)
```

## Parallel dataflow

Parallel dataflows can be developed by passing data between Apps. In this example we create a set of files, each with a random number, we then concatenate these files into a single file and compute the sum of all numbers in that file. The calls to the first App each create a file, and the second App reads these files and creates a new one. The final App returns the sum as a Python integer.

```python
# App that generates a semi-random number between 0 and 32,767
@bash_app
def generate(outputs):
    return "echo $(( RANDOM )) &> {}".format(outputs[0])

# App that concatenates input files into a single output file
@bash_app
def concat(inputs, outputs):
    return "cat {0} > {1}".format(" ".join([i.filepath for i in inputs]), outputs[0])

# App that calculates the sum of values in a list of input files
@python_app
def total(inputs):
    total = 0
    with open(inputs[0], 'r') as f:
        for l in f:
            total += int(l)
    return total

# Create 5 files with semi-random numbers in parallel
output_files = []
for i in range (5):
     output_files.append(generate(outputs=[File(os.path.join(os.getcwd(), 'random-{}.txt'.format(i)))]))

# Concatenate the files into a single file
cc = concat(inputs=[i.outputs[0] for i in output_files],
            outputs=[File(os.path.join(os.getcwd(), 'all.txt'))])

# Calculate the sum of the random numbers
total = total(inputs=[cc.outputs[0]])
print (total.result())
```

# Dynamic workflows with apps that generate other apps

Often there is a need for a workflow to launch apps based on results from prior apps, but it doesn’t know what those apps are until some earlier apps are completed. For example, a pre-processing stage might be followed by n middle stages, but the value of n is not known until pre-processing is complete; or the choice of app to run might depend on the output of pre-processing.

Parsl’s `join_app` is designed to address this situation by allowing you to define sub-workflows. Rather than return a value, like `python_app`, a `join_app` instead returns a future. When invoked, the `join_app` will not complete until the future has completed and the return value will be the return value from the future.

The following example shows how recursive Fibonacci can be implemented using a `join_app`. Here the fibonacci app makes calls to a seperate add app for each pair of numbers.

```python
from parsl.app.app import join_app, python_app

@python_app
def add(*args):
    """Add all of the arguments together. If no arguments, then
    zero is returned (the neutral element of +)
    """
    accumulator = 0
    for v in args:
        accumulator += v
    return accumulator


@join_app
def fibonacci(n):
    if n == 0:
        return add()
    elif n == 1:
        return add(1)
    else:
        return add(fibonacci(n - 1), fibonacci(n - 2))

print(fibonacci(10).result())
```

# Examples

## Monte Carlo workflow

Many scientific applications use the Monte Carlo method to compute results.

One example is calculating π by randomly placing points in a box and using the ratio that are placed inside the circle.

Specifically, if a circle with radius r is inscribed inside a square with side length 2r, the area of the circle is πr² and the area of the square is 4r².

Thus, if N uniformly-distributed random points are dropped within the square, approximately Nπ/4 will be inside the circle.

Each call to the function `pi()` is executed independently and in parallel. The `avg_three()` app is used to compute the average of the futures that were returned from the `pi()` calls.

The dependency chain looks like this:

```text
App Calls    pi()  pi()   pi()
              \     |     /
Futures        a    b    c
                \   |   /
App Call        avg_points()
                    |
Future            avg_pi
```

```python
# App that estimates pi by placing points in a box
@python_app
def pi(num_points):
    from random import random

    inside = 0
    for i in range(num_points):
        x, y = random(), random()  # Drop a random point in the box.
        if x**2 + y**2 < 1:        # Count points within the circle.
            inside += 1

    return (inside*4 / num_points)

# App that computes the mean of three values
@python_app
def mean(a, b, c):
    return (a + b + c) / 3

# Estimate three values for pi
a, b, c = pi(10**6), pi(10**6), pi(10**6)

# Compute the mean of the three estimates
mean_pi  = mean(a, b, c)

# Print the results
print("a: {:.5f} b: {:.5f} c: {:.5f}".format(a.result(), b.result(), c.result()))
print("Average: {:.5f}".format(mean_pi.result()))
```

# Execution and configuration

Parsl is designed to support arbitrary execution providers, such as PCs, clusters, supercomputers, and clouds, and execution models, such as threads and pilot jobs. The configuration used to run the script tells Parsl how to execute apps on the desired environment. Parsl provides a high level abstraction, called a Block, for describing the resource configuration for a particular app or script.

Information about the different execution providers and executors supported is included in the Parsl documentation.

So far in this tutorial, we’ve used a built-in configuration for running with threads. Below, we will illustrate how to create configs for different environments.

## Local execution with threads

As we saw above, we can configure Parsl to execute apps on a local thread pool. This is a good way to parallelize execution on a local PC. The configuration object defines the executors that will be used as well as other options such as authentication method, for example if using SSH, checkpoint files, and executor specific configuration. In the case of threads we define the maximum number of threads to be used.

```python
from parsl.config import Config
from parsl.executors.threads import ThreadPoolExecutor

local_threads = Config(
    executors=[
        ThreadPoolExecutor(
            max_threads=8,
            label='local_threads'
        )
    ]
)
```

