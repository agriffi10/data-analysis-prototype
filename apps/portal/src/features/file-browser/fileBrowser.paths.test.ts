import {describe, it, expect} from 'vitest';
import {leafName, fileParent, folderParts, lastSegment, fileExtension} from './fileBrowser.paths';

describe('fileBrowser.paths', () => {
  it('leafName returns the last segment of a file key', () => {
    expect(leafName('a/b/c.txt')).toBe('c.txt');
    expect(leafName('c.txt')).toBe('c.txt');
  });

  it('fileParent returns the parent prefix of a file key', () => {
    expect(fileParent('a/b/c.txt')).toBe('a/b/');
    expect(fileParent('c.txt')).toBe('');
  });

  it('folderParts splits a folder prefix into parent + leaf', () => {
    expect(folderParts('a/b/photos/')).toEqual({parent: 'a/b/', leaf: 'photos'});
    expect(folderParts('photos/')).toEqual({parent: '', leaf: 'photos'});
  });

  it('lastSegment tolerates a trailing slash (files and folders)', () => {
    expect(lastSegment('a/b/photos/')).toBe('photos');
    expect(lastSegment('a/b/c.txt')).toBe('c.txt');
  });

  it('fileExtension uppercases the extension with a fallback + optional cap', () => {
    expect(fileExtension('report.pdf')).toBe('PDF');
    expect(fileExtension('noext')).toBe('File');
    expect(fileExtension('noext', {fallback: 'FILE'})).toBe('FILE');
    expect(fileExtension('archive.tarball', {maxLen: 4})).toBe('TARB');
    expect(fileExtension('.gitignore')).toBe('File'); // leading dot → no ext
  });
});
