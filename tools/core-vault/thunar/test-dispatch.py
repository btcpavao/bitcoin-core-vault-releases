#!/usr/bin/python3
"""Compile and test the exact patched C dispatcher with a non-destructive spawn spy."""
from pathlib import Path
import argparse, os, shlex, subprocess, tempfile

PRELUDE = r'''
#include <gio/gio.h>
#include <stdio.h>
#include <string.h>
#define _(s) (s)
static guint spawn_count, error_count;
static gboolean should_fail;
static gchar **captured;
static gboolean fake_spawn (const gchar *cwd, gchar **argv, gchar **env,
                           GSpawnFlags flags, GSpawnChildSetupFunc setup,
                           gpointer data, GPid *pid, GError **error)
{
  g_assert_null (cwd); g_assert_null (env); g_assert_cmpint (flags, ==, 0);
  g_assert_null (setup); g_assert_null (data); g_assert_null (pid);
  ++spawn_count; g_strfreev (captured); captured = g_strdupv (argv);
  if (should_fail) { g_set_error_literal (error, G_SPAWN_ERROR,
                           G_SPAWN_ERROR_NOENT, "Synthetic missing helper"); return FALSE; }
  return TRUE;
}
#define g_spawn_async fake_spawn
static void thunar_dialogs_show_error (gpointer parent, GError *error, const gchar *text)
{
  g_assert_null (parent); g_assert_nonnull (error);
  g_assert_nonnull (text); ++error_count;
}
'''

TESTS = r'''
static GList *local (const gchar *name)
{
  return g_list_append (NULL, g_file_new_for_path (name));
}
int main (void)
{
  const gchar *odd = "/synthetic/-leading space ' quote $() ;\nline\tfile";
  GList *files = local (odd);
  files = g_list_append (files, g_file_new_for_path ("/synthetic/folder/item"));
  g_assert_true (core_vault_shred_files (NULL, files));
  g_assert_cmpuint (spawn_count, ==, 1);
  g_assert_cmpuint (g_strv_length (captured), ==, 4);
  g_assert_cmpstr (captured[0], ==, "/usr/local/bin/core-vault-shred");
  g_assert_cmpstr (captured[1], ==, "--");
  g_assert_cmpstr (captured[2], ==, odd);
  g_assert_cmpstr (captured[3], ==, "/synthetic/folder/item");
  g_list_free_full (files, g_object_unref);

  g_assert_true (core_vault_shred_files (NULL, NULL));
  g_assert_cmpuint (spawn_count, ==, 1);

  files = local ("/synthetic/local-must-not-launch-with-invalid-second-item");
  files = g_list_append (files, g_file_new_for_uri ("trash:///old-item"));
  g_assert_true (core_vault_shred_files (NULL, files));
  g_assert_cmpuint (spawn_count, ==, 1);
  g_assert_cmpuint (error_count, ==, 1);
  g_list_free_full (files, g_object_unref);

  files = g_list_append (NULL, g_file_new_for_uri ("sftp://example.invalid/a"));
  g_assert_true (core_vault_shred_files (NULL, files));
  g_assert_cmpuint (spawn_count, ==, 1);
  g_assert_cmpuint (error_count, ==, 2);
  g_list_free_full (files, g_object_unref);

  should_fail = TRUE;
  files = local ("/synthetic/missing-helper-keeps-file");
  g_assert_true (core_vault_shred_files (NULL, files));
  g_assert_cmpuint (spawn_count, ==, 2);
  g_assert_cmpuint (error_count, ==, 3);
  g_list_free_full (files, g_object_unref);
  g_strfreev (captured);
  puts ("PASS: literal multiple arguments, no shell/PATH, local-only, empty selection, mixed/remote refusal, missing helper error, Undo suppressed; no files changed.");
  return 0;
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('prefix',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    text=(a.source/'thunar/thunar-application.c').read_text()
    start=text.index('/* CORE_VAULT_SHRED_V1:')
    end=text.index('\n\n\nstatic ThunarJob *\nunlink_stub',start)
    function=text[start:end]
    for forbidden in ['g_spawn_command_line','g_file_delete','thunar_io_jobs_unlink_files',
                      'thunar_io_jobs_trash_files','system (','G_SPAWN_SEARCH_PATH']:
        if forbidden in function: raise RuntimeError('Unsafe dispatcher: '+forbidden)
    a.output.mkdir(exist_ok=True)
    c=a.output/'dispatch-test.c';c.write_text(PRELUDE+function+TESTS)
    env=os.environ.copy()
    env.update({'PKG_CONFIG_SYSROOT_DIR':str(a.prefix),
                'PKG_CONFIG_LIBDIR':str(a.prefix/'usr/lib/x86_64-linux-gnu/pkgconfig'),
                'LD_LIBRARY_PATH':str(a.prefix/'usr/lib/x86_64-linux-gnu')})
    pc=a.prefix/'usr/bin/pkgconf'
    flags=shlex.split(subprocess.check_output([str(pc),'--cflags','--libs','gio-2.0'],env=env,text=True))
    executable=a.output/'dispatch-test'
    subprocess.run(['gcc','-Wall','-Wextra','-Werror',str(c),'-o',str(executable),*flags],env=env,check=True)
    subprocess.run([str(executable)],env=env,check=True)

if __name__=='__main__':
    main()
