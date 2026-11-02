#!/usr/bin/python3
"""Patch Debian Thunar 4.20.2 for the explicit Vault permanent-delete helper."""
from pathlib import Path
import argparse, difflib, hashlib, re

HASHES = {
    'thunar/thunar-action-manager.c': '904e437d348807d34557fbda74c1a8637fdc46494b129341d2a4fc14a8f5a0a5',
    'thunar/thunar-application.c': 'da922f635d6a7ce2e44bcca54b3d0cbb16bb0d25857f2576ccaabe6f5404fc41',
}

DISPATCH = r'''/* CORE_VAULT_SHRED_V1: argv-only dispatch; the helper owns confirmation and
 * file-system checks. Never fall back to the ordinary trash/unlink jobs.
 * Permanent deletion cannot be undone, so return TRUE to suppress the
 * operation log's ordinary delete/undo assumptions even after spawning. */
static gboolean
core_vault_shred_files (gpointer parent,
                       GList   *file_list)
{
  GPtrArray *argv;
  GList     *lp;
  GError    *error = NULL;
  gchar     *path;

  if (file_list == NULL)
    return TRUE;

  argv = g_ptr_array_new_with_free_func (g_free);
  g_ptr_array_add (argv, g_strdup ("/usr/local/bin/core-vault-shred"));
  g_ptr_array_add (argv, g_strdup ("--"));

  for (lp = file_list; lp != NULL; lp = lp->next)
    {
      if (!G_IS_FILE (lp->data) || !g_file_is_native (lp->data))
        {
          g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_NOT_SUPPORTED,
                               _("Permanent deletion is available only for local files. Trash and remote locations are not supported."));
          goto failed;
        }
      path = g_file_get_path (lp->data);
      if (path == NULL || path[0] != '/')
        {
          g_free (path);
          g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                               _("A local absolute path is required for permanent deletion."));
          goto failed;
        }
      g_ptr_array_add (argv, path);
    }
  g_ptr_array_add (argv, NULL);

  /* GLib reaps this child. No shell, PATH search, flags, or URI arguments. */
  if (!g_spawn_async (NULL, (gchar **) argv->pdata, NULL, 0,
                      NULL, NULL, NULL, &error))
    goto failed;
  g_ptr_array_unref (argv);
  return TRUE;

failed:
  thunar_dialogs_show_error (parent, error,
                            _("Unable to start permanent deletion"));
  g_clear_error (&error);
  g_ptr_array_unref (argv);
  return TRUE;
}
'''

UNLINK = r'''{
  GList *paths = NULL;
  GList *lp;

  _thunar_return_val_if_fail (parent == NULL || GDK_IS_SCREEN (parent) || GTK_IS_WIDGET (parent), TRUE);
  _thunar_return_val_if_fail (THUNAR_IS_APPLICATION (application), TRUE);
  (void) permanently;
  (void) warn;
  (void) log_mode;

  for (lp = file_list; lp != NULL; lp = lp->next)
    {
      if (!THUNAR_IS_FILE (lp->data))
        {
          thunar_g_list_free_full (paths);
          return TRUE;
        }
      paths = g_list_append (paths, g_object_ref (thunar_file_get_file (lp->data)));
    }
  core_vault_shred_files (parent, paths);
  thunar_g_list_free_full (paths);
  return TRUE;
}'''

TRASH = r'''{
  _thunar_return_if_fail (parent == NULL || GDK_IS_SCREEN (parent) || GTK_IS_WIDGET (parent));
  _thunar_return_if_fail (THUNAR_IS_APPLICATION (application));
  (void) log_mode;
  core_vault_shred_files (parent, file_list);
}'''

EMPTY = r'''{
  _thunar_return_if_fail (THUNAR_IS_APPLICATION (application));
  _thunar_return_if_fail (parent == NULL || GDK_IS_SCREEN (parent) || GTK_IS_WIDGET (parent));
  (void) startup_id;
  thunar_dialogs_show_error (parent, NULL,
                            _("Trash is unavailable in Bitcoin Core Vault. Select local files and choose Permanently Delete."));
}'''

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected source anchor: '+old[:100])
    return text.replace(old, new)

def body(text, name, replacement):
    match = re.search(r'^'+re.escape(name)+r' \([^;]+?\)\n\{', text, re.M)
    if not match:
        raise RuntimeError('Missing function '+name)
    start = text.index('{', match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[:start]+replacement+text[end:]

def patched(name, text):
    if name.endswith('thunar-action-manager.c'):
        text = once(text, 'N_ ("Mo_ve to Trash")', 'N_ ("Permanently _Delete…")')
        # Replace the icon in exactly this native action entry, not other trash icons.
        lines = text.splitlines(keepends=True)
        for i,line in enumerate(lines):
            if '{THUNAR_ACTION_MANAGER_ACTION_MOVE_TO_TRASH,' in line:
                lines[i] = once(line, '"user-trash"', '"edit-delete"')
        text = ''.join(lines)
        text = body(text, 'thunar_action_manager_show_trash',
                    '{\n  /* Show one permanent-delete action on local selections, including removable media. */\n  return action_mgr->parent_folder != NULL;\n}')
        start = text.index('    case THUNAR_ACTION_MANAGER_ACTION_DELETE:\n')
        end = text.index('    case THUNAR_ACTION_MANAGER_ACTION_EMPTY_TRASH:\n', start)
        text = text[:start]+'''    case THUNAR_ACTION_MANAGER_ACTION_DELETE:
      /* The native former Trash item is now the single permanent-delete entry.
       * Delete and Shift+Delete accelerators still dispatch through the helper. */
      return NULL;

'''+text[end:]
        text = once(text, '  gboolean                  show_delete_item;\n', '')
        text = once(text, 'ngettext ("Move the selected file to the Trash",\n                               "Move the selected files to the Trash"',
                    'ngettext ("Overwrite and permanently delete the selected file",\n                               "Overwrite and permanently delete the selected files"')
        return text
    text = once(text, 'static ThunarJob *\nunlink_stub', DISPATCH+'\n\nstatic ThunarJob *\nunlink_stub')
    text = body(text, 'thunar_application_unlink_files', UNLINK)
    text = body(text, 'thunar_application_trash', TRASH)
    text = body(text, 'thunar_application_empty_trash', EMPTY)
    # The unlinked/trash job stubs are no longer used by native delete actions.
    text = body(text, 'unlink_stub', '{\n  /* Disabled: native deletion must never invoke an ordinary unlink job. */\n  (void) source_path_list;\n  (void) target_path_list;\n  return NULL;\n}')
    text = body(text, 'trash_stub', '{\n  (void) source_file_list;\n  (void) target_file_list;\n  return NULL;\n}')
    return text

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--diff', type=Path)
    args=parser.parse_args()
    patches=[]
    changes=[]
    for name,expected in HASHES.items():
        p=args.source/name
        old=p.read_text()
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Unexpected Debian base source: '+name)
        new=patched(name,old)
        changes.append((p,new))
        patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                          fromfile='a/'+name,tofile='b/'+name))
    if args.diff:
        args.diff.write_text(''.join(patches))
    for p,new in changes:
        p.write_text(new)
    print('VAULT THUNAR PERMANENT-DELETE SOURCE PATCH PASSED')

if __name__ == '__main__':
    main()
