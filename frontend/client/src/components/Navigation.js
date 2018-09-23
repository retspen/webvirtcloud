import React, { Component } from "react";
import {Link} from "react-router-dom";
import PropTypes from 'prop-types';
import { withStyles } from '@material-ui/core/styles';
import Toolbar from '@material-ui/core/Toolbar';
import AppBar from '@material-ui/core/AppBar';
import MenuItem from '@material-ui/core/MenuItem';
import Menu from '@material-ui/core/Menu';
import IconButton from '@material-ui/core/IconButton';
import Typography from '@material-ui/core/Typography';
import AccountCircle from '@material-ui/icons/AccountCircle';

const styles = {
  root: {
    flexGrow: 1,
  },
  title: {
    textDecoration: 'none',
    flexGrow: 1,
  },
  menuButton: {
    marginLeft: -12,
    marginRight: 20,
  },
};

class Navigation extends Component {
  state = {
    anchorEl: null,
  };

  handleMenu = event => {
    this.setState({ anchorEl: event.currentTarget });
  };

  handleClose = () => {
    this.setState({ anchorEl: null });
  };

  render() {
    const { classes } = this.props;
    const { anchorEl } = this.state;
    const open = Boolean(anchorEl);

    return (
      <AppBar position="static">
        <Toolbar>
          <Typography component={Link} to="/" variant="title" color="inherit" className={classes.title}>Webvirtcloud</Typography>
          <div>
            <IconButton
              aria-owns={open ? 'menu-appbar' : null}
              aria-haspopup="true"
              onClick={this.handleMenu}
              color="inherit"
            >
              <AccountCircle />
            </IconButton>
            <Menu
              id="menu-appbar"
              anchorEl={anchorEl}
              anchorOrigin={{
                vertical: 'top',
                horizontal: 'right',
              }}
              transformOrigin={{
                vertical: 'top',
                horizontal: 'right',
              }}
              open={open}
              onClose={this.handleClose}
            >
              <MenuItem component={Link} to="/profile" onClick={this.handleClose}>Profile</MenuItem>
              <MenuItem component={Link} to="/auth/signin" onClick={this.handleClose}>Log out</MenuItem>
            </Menu>
          </div>
        </Toolbar>
      </AppBar>
    )
  }
}

Navigation.propTypes = {
  classes: PropTypes.object.isRequired,
};

export default withStyles(styles)(Navigation);
