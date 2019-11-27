from setuptools import setup


setup(name='popoto', version='1.1', description='Popoto Shell and interface for Acoustic Modem',
	url='http://github.com/delresearch/popoto_Py_API', author='Popoto Modem', author_email='info@popotomodem.com',
	license='MIT', packages=['popoto'], install_requires=['cmd2'],
	scripts=['popoto/bin/pshell'],
	 zip_safe=False)

