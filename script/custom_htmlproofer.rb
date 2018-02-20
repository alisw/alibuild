#!/usr/bin/env ruby
require 'html-proofer'
HTMLProofer.check_directory("./_site",
                            :parallel => { :in_processes => 3 },
                            :typhoeus => { :timeout => 100, :ssl_verifyhost => 2 }).run
